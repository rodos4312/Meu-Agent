"""Chat -> registry -> real CodingTaskService, Git worktrees and subprocess checks.

Only the model and human are deterministic. The task, audit, patch, diff, recovery,
project selection and test commands are real; this is not live-provider/device proof.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hermes_cli import projects_db
from meu_coding.safe_execution import SafeExecutionAdapter
from meu_coding.task_service import CodingTaskService, ModelBundle
from meu_coding.test_executor import RunOutcome, TestExecutor
from tests.meu_coding.phase3_support import make_git_repo, ScriptedModel, good, git, snapshot
from tools import coding_task_tool, terminal_tool  # registers the tool
from tools.registry import registry


@pytest.fixture
def setup_chat(tmp_path, monkeypatch):
    repo = make_git_repo(tmp_path)
    calls = []

    def run(argv, cwd, env, timeout):
        argv = [sys.executable if a in {"python", "python3"} else a for a in argv]
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        calls.append((argv, cwd, result.returncode))
        return RunOutcome(result.returncode, result.stdout, result.stderr)

    def service(spawn=lambda fn, name: fn()):
        return CodingTaskService(
            models_factory=lambda: ModelBundle(None, ScriptedModel([good]), None,
                                                {"coder": "test:deterministic"}, "test"),
            adapter_factory=lambda: SafeExecutionAdapter(executor_factory=lambda root, extra: TestExecutor(
                root, runner=run, extra_test_targets=extra)),
            spawn=spawn, audit_directory=tmp_path / "audit")

    engine = service()
    from meu_coding import service_registry
    monkeypatch.setattr(service_registry, "current_service", lambda: engine)
    with projects_db.connect_closing() as conn:
        projects_db.create_project(conn, name="Το έργο μου", folders=[str(repo)], primary_path=str(repo))
        other = projects_db.create_project(conn, name="Άλλη συνομιλία", folders=[str(tmp_path)])
        projects_db.set_active(conn, other)
    terminal_tool.register_task_env_overrides("chat-runtime", {"cwd_source": "session", "cwd": str(repo)})
    yield repo, engine, calls, service
    terminal_tool.clear_task_env_overrides("chat-runtime")


def call(action="start", **args):
    return json.loads(registry.dispatch("coding_task", {"action": action, **args},
        task_id="chat-runtime", session_id="chat-1", turn_id="admission-1", tool_call_id="call-1"))


def test_chat_real_worktree_tests_results_and_duplicate_retry(setup_chat, monkeypatch):
    repo, engine, calls, _ = setup_chat
    before = snapshot(repo)
    approvals = []
    def approve(view):
        approvals.append(view["approval"]["fingerprint"])
        return "approve"
    monkeypatch.setattr("tools.coding_task_approval.ask_coding_approval", approve)
    result = call(description="Πρόσθεσε συνάρτηση add στο calc/ops.py και αντίστοιχο test.",
                  files=["calc/ops.py", "tests/test_ops.py"])
    assert result["stage"] == "awaiting_keep_reject", result
    assert Path(result["project"]) == repo
    assert result["execution"]["reviewer"]["verdict"] == "pass"
    assert calls and all(code == 0 for _, _, code in calls)
    assert any("pytest" in argv for argv, _, _ in calls)
    worktree = Path(result["execution"]["worktree"]["path"])
    assert "def add" in (worktree / "calc/ops.py").read_text()
    assert snapshot(repo) == before
    assert git(repo, "status", "--porcelain") == ""
    retry = call(description="Πρόσθεσε συνάρτηση add στο calc/ops.py και αντίστοιχο test.",
                 files=["calc/ops.py", "tests/test_ops.py"])
    assert retry["task_id"] == result["task_id"] and len(engine.tasks) == 1
    assert len(approvals) == 1
    assert call("status")["task_id"] == result["task_id"]


@pytest.mark.parametrize("choice,stage", [("reject", "rejected"), ("unanswered", "awaiting_approval")])
def test_denial_or_no_human_never_executes(setup_chat, monkeypatch, choice, stage):
    repo, _engine, calls, _ = setup_chat
    monkeypatch.setattr("tools.coding_task_approval.ask_coding_approval", lambda view: choice)
    result = call(description="Add add to calc/ops.py", files=["calc/ops.py", "tests/test_ops.py"])
    assert result["stage"] == stage, result
    assert not calls and not (repo / ".worktrees").exists()


def test_restart_and_concurrent_retry_reuse_durable_task_without_execution(setup_chat, monkeypatch):
    repo, _, calls, factory = setup_chat
    pending = []
    engine = factory(lambda fn, name: pending.append(fn))
    with ThreadPoolExecutor(max_workers=4) as pool:
        views = list(pool.map(lambda _: engine.start_chat("Add add", str(repo), "chat-1", "turn-1"), range(4)))
    assert len({v["task_id"] for v in views}) == len(pending) == 1
    recovered = factory()
    view = recovered.start_chat("Add add", str(repo), "chat-1", "turn-1")
    assert view["task_id"] == views[0]["task_id"]
    assert view["restored"] and view["stage"] in {"failed", "interrupted"}
    assert not calls
    with pytest.raises(Exception, match="another conversation"):
        recovered.chat_task("other-chat", view["task_id"])


def test_missing_project_and_missing_identity_are_actionable(setup_chat):
    terminal_tool.register_task_env_overrides("chat-runtime", {"cwd_source": "session", "cwd": ""})
    result = call(description="Fix bug")
    assert result["workflow"] == "chat" and result["workspace"] is None
    assert not result["engine_task_started"]
    no_identity = json.loads(registry.dispatch("coding_task", {"action": "start", "description": "Fix"}))
    assert "identity" in no_identity["error"]


def test_mandatory_approval_ignores_yolo_and_uses_one_operation_buttons(monkeypatch):
    from tools import approval, approval_gateway_wait
    from tools.approval_context import set_current_session_key, reset_current_session_key
    from tools.coding_task_approval import ask_coding_approval
    seen = []
    monkeypatch.setenv("HERMES_YOLO", "1")
    monkeypatch.setattr(approval, "_gateway_notify_cbs", {"chat-approval": lambda data: None})
    def wait(key, callback, data, surface):
        seen.append(data)
        return {"resolved": True, "choice": "once"}
    monkeypatch.setattr(approval_gateway_wait, "_await_gateway_decision", wait)
    binding = set_current_session_key("chat-approval")
    try:
        view = {"task_id": "abc", "project": "project", "approval": {
            "fingerprint": "exact-fingerprint", "approval_id": "proposal", "proposed_diff": "+ new code"}}
        assert ask_coding_approval(view) == "approve"
    finally:
        reset_current_session_key(binding)
    assert seen[0]["allow_permanent"] is seen[0]["allow_session"] is False
    assert "exact-fingerprint" in seen[0]["command"]


def test_real_tool_failure_is_returned_without_fake_success(setup_chat, monkeypatch):
    _, engine, _, _ = setup_chat
    def fail():
        raise ValueError("No coding model configured")
    monkeypatch.setattr(engine, "models_factory", fail)
    result = call(description="Fix the bug")
    assert "error" in result and "stage" not in result
    assert not engine.tasks


@pytest.mark.parametrize("choice,stage", [("once", "awaiting_keep_reject"), ("deny", "rejected")])
def test_real_gateway_approval_queue_and_progress(setup_chat, choice, stage):
    from tools import approval
    from tools.approval_context import set_current_session_key, reset_current_session_key
    from agent.tool_progress_relay import bound_tool_progress
    _repo, _engine, calls, _ = setup_chat
    events = []
    cards = []
    def notify(card):
        cards.append(card)
        assert approval.resolve_gateway_approval("coding-chat", choice, request_id=card["request_id"]) == 1
    approval.register_gateway_notify("coding-chat", notify)
    binding = set_current_session_key("coding-chat")
    try:
        with bound_tool_progress(lambda *a, **kw: events.append((a, kw)), "coding_task", "call-1"):
            result = call(description="Add add to calc/ops.py with a unit test",
                          files=["calc/ops.py", "tests/test_ops.py"])
    finally:
        reset_current_session_key(binding)
        approval.unregister_gateway_notify("coding-chat")
    assert result["stage"] == stage, result
    assert len(cards) == 1 and events
    assert result["task_id"] in cards[0]["command"]
    assert events[0][0][0] == "tool.progress" and result["task_id"][:8] in events[0][0][2]
    assert events[0][1]["percent"] is None
    assert bool(calls) is (choice == "once")


def test_selected_remote_backend_is_not_silently_executed_on_host(setup_chat):
    repo, engine, calls, _ = setup_chat
    terminal_tool.register_task_env_overrides("chat-runtime", {
        "cwd_source": "session", "cwd": str(repo), "env_type": "ssh"})
    result = call(description="Fix my project")
    assert "not local" in result["error"] and not engine.tasks and not calls


def test_dispatcher_forwards_trusted_identity_not_model_arguments(setup_chat, monkeypatch):
    from model_tools import handle_function_call
    _, engine, _, _ = setup_chat
    monkeypatch.setattr("tools.coding_task_approval.ask_coding_approval", lambda view: "unanswered")
    result = json.loads(handle_function_call("coding_task", {
        "action": "start", "description": "Add add to calc/ops.py", "session_id": "forged",
        "turn_id": "forged", "files": ["calc/ops.py", "tests/test_ops.py"]},
        task_id="chat-runtime", session_id="trusted-chat", turn_id="trusted-turn", tool_call_id="tool-1"))
    record = engine.tasks[result["task_id"]]
    assert record.audit.chat_session_id == "trusted-chat"
    with pytest.raises(Exception, match="another conversation"):
        engine.chat_task("forged", result["task_id"])


def test_chat_scoped_home_selects_existing_service_and_audit(tmp_path):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from meu_coding.service_registry import current_service
    bindings = []
    try:
        bindings.append(set_hermes_home_override(tmp_path / "profile-a"))
        a = current_service()
        bindings.append(set_hermes_home_override(tmp_path / "profile-b"))
        b = current_service()
        assert a is not b
        reset_hermes_home_override(bindings.pop())
        assert current_service() is a
    finally:
        for binding in reversed(bindings):
            reset_hermes_home_override(binding)


def test_recovered_execution_is_interrupted_never_completed(setup_chat):
    from meu_coding import task_audit
    repo, engine, calls, factory = setup_chat
    record = task_audit.AuditRecord("a" * 32, str(repo), "work", chat_session_id="chat-1",
                                    chat_request_id="request")
    record.stage("executing")
    task_audit.save(record, engine.audit_directory)
    recovered = factory()
    result = recovered.chat_task("chat-1", record.task_id)
    assert result["stage"] == "interrupted" and result["restored"]
    assert not result["actions"]["approve"] and not calls


def test_no_audit_write_means_no_worker_started(setup_chat, monkeypatch):
    from meu_coding import task_audit
    repo, _, _, factory = setup_chat
    workers = []
    engine = factory(lambda fn, name: workers.append(fn))
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(task_audit, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        engine.start_chat("Fix", str(repo), "chat", "turn")
    assert not workers and not engine.tasks


def test_natural_chat_turn_reaches_real_engine_and_returns_tool_result(setup_chat, monkeypatch):
    """Real agent turn/registry/engine; provider output is deterministic, not live-provider proof."""
    from types import SimpleNamespace as NS
    from run_agent import AIAgent
    from tools import approval
    from tools.approval_context import set_current_session_key, reset_current_session_key
    _, engine, commands, _ = setup_chat
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        tools = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        if not tools:
            tool = NS(id="coding-call", type="function", function=NS(name="coding_task", arguments=json.dumps({
                "action": "start", "description": "Πρόσθεσε add στο calc/ops.py και test",
                "files": ["calc/ops.py", "tests/test_ops.py"]})))
            message = NS(content=None, reasoning=None, tool_calls=[tool])
            reason = "tool_calls"
        else:
            data = json.loads(tools[-1]["content"])
            assert data["stage"] == "awaiting_keep_reject", data
            message = NS(content="Το αποτέλεσμα είναι έτοιμο για αξιολόγηση: " + data["task_id"],
                         reasoning=None, tool_calls=[])
            reason = "stop"
        return NS(choices=[NS(message=message, finish_reason=reason)], usage=None)
    client = NS(chat=NS(completions=NS(create=create)))
    monkeypatch.setattr("agent.process_bootstrap.OpenAI", lambda **kw: client)
    approval.register_gateway_notify("natural-chat", lambda card: approval.resolve_gateway_approval(
        "natural-chat", "once", request_id=card["request_id"]))
    binding = set_current_session_key("natural-chat")
    agent = AIAgent(model="test-model", api_key="test-key", base_url="http://localhost:9999/v1",
                    session_id="chat-1", platform="cli", enabled_toolsets=["project"], max_iterations=3,
                    quiet_mode=True, skip_memory=True, skip_context_files=True, save_trajectories=False)
    agent._disable_streaming = True
    try:
        result = agent.run_conversation("Πρόσθεσε στο έργο μου συνάρτηση πρόσθεσης και δοκίμασέ την.",
                                        task_id="chat-runtime")
    finally:
        reset_current_session_key(binding)
        approval.unregister_gateway_notify("natural-chat")
    assert len(engine.tasks) == 1 and commands
    task = next(iter(engine.tasks.values()))
    assert task.task_id in result["final_response"]
    assert any(t["function"]["name"] == "coding_task" for t in requests[0]["tools"])
    assert task.audit.chat_session_id == "chat-1"


def test_named_existing_project_uses_existing_session_workspace_switch(setup_chat, monkeypatch):
    repo, _engine, calls, _ = setup_chat
    switches = []
    from tools import project_tools
    monkeypatch.setattr(project_tools, "_workspace_callback", lambda tid, path, name: switches.append((tid, path, name)))
    monkeypatch.setattr("tools.coding_task_approval.ask_coding_approval", lambda view: "reject")
    result = call(description="Add add with tests", project_name="Το έργο μου", files=["calc/ops.py", "tests/test_ops.py"])
    assert result["stage"] == "rejected", result
    assert Path(result["project"]) == repo
    assert len(switches) == 1
    assert switches[0][0] == "chat-runtime" and Path(switches[0][1]) == repo
    assert switches[0][2] == "Το έργο μου"
    assert not calls
    from hermes_cli import projects_db
    with projects_db.connect_closing() as conn:
        active = projects_db.get_active_id(conn)
        assert projects_db.get_project(conn, active).name == "Άλλη συνομιλία"


def test_unknown_project_never_guesses_a_folder_or_starts_work(setup_chat):
    repo, engine, calls, _ = setup_chat
    result = call(description="Implement feature", project_name="Not registered")
    assert "existing project exactly" in result["error"]
    assert not engine.tasks and not calls and not (repo / ".worktrees").exists()


def test_non_git_project_routes_back_to_chat_without_models_or_approval(setup_chat, tmp_path, monkeypatch):
    from tools import project_tools
    repo, engine, checks, _ = setup_chat
    folder = tmp_path / "Νέο έργο"
    folder.mkdir()
    (folder / "existing.txt").write_text("owner data", encoding="utf-8")
    project_tools.project_create("Νέο έργο", path=str(folder))
    terminal_tool.register_task_env_overrides("chat-runtime", {"cwd_source": "session", "cwd": str(folder)})
    def forbidden(*args, **kwargs):
        raise AssertionError("Ordinary creation must not start the engine or ask for its approval")
    monkeypatch.setattr("meu_coding.service_registry.current_service", forbidden)
    monkeypatch.setattr("tools.coding_task_approval.ask_coding_approval", forbidden)
    before = snapshot(repo)
    result = call(description="Φτιάξε μια εφαρμογή σημειώσεων")
    assert result["workflow"] == "chat" and Path(result["workspace"]) == folder
    assert not result["engine_task_started"] and not engine.tasks and not checks
    assert (folder / "existing.txt").read_text() == "owner data"
    assert not (folder / ".git").exists() and snapshot(repo) == before


def test_unregistered_git_workspace_uses_engine_without_project_setup(setup_chat, monkeypatch):
    repo, engine, checks, _ = setup_chat
    with projects_db.connect_closing() as conn:
        conn.execute("DELETE FROM projects")
        conn.commit()
    monkeypatch.setattr("tools.coding_task_approval.ask_coding_approval", lambda view: "approve")
    result = call(description="Add add", files=["calc/ops.py", "tests/test_ops.py"])
    assert result["stage"] == "awaiting_keep_reject", result
    assert Path(result["project"]) == repo and len(engine.tasks) == 1 and checks
    assert "worktree folder" in result["notice"]
    assert "Do not force" in result["notice"]


def test_unavailable_selected_workspace_is_not_a_chat_fallback(setup_chat, tmp_path):
    from tools import project_tools
    repo, engine, checks, _ = setup_chat
    project_tools.project_create("Missing", path=str(tmp_path / "gone"))
    result = call(description="Fix existing program", project_name="Missing")
    assert "workspace is unavailable" in result["error"]
    assert not engine.tasks and not checks and not (repo / ".worktrees").exists()


def test_new_program_in_chat_writes_real_file_without_git_or_engine(setup_chat, tmp_path, monkeypatch):
    """Real agent turn, dispatcher and file write; deterministic provider, not a live LLM test."""
    from types import SimpleNamespace as NS
    from run_agent import AIAgent
    folder = tmp_path / "fresh-workspace"
    folder.mkdir()
    terminal_tool.register_task_env_overrides("chat-runtime", {"cwd_source": "session", "cwd": str(folder)})
    _, engine, checks, _ = setup_chat
    source = "def total(values):\n    return sum(values)\n\nif __name__ == '__main__':\n    print(total([2, 3, 5]))\n"
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        results = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        if len(results) == 0:
            name, arguments = "coding_task", {"action": "start", "description": "Φτιάξε ένα μικρό πρόγραμμα"}
        elif len(results) == 1:
            data = json.loads(results[-1]["content"])
            assert data["workflow"] == "chat" and not data["engine_task_started"]
            name, arguments = "write_file", {"path": "my-program/app.py", "content": source}
        else:
            data = json.loads(results[-1]["content"])
            assert "error" not in data, data
            message = NS(content="Το αρχείο είναι στο my-program/app.py", reasoning=None, tool_calls=[])
            return NS(choices=[NS(message=message, finish_reason="stop")], usage=None)
        tool = NS(id=f"call-{len(results)}", type="function", function=NS(name=name, arguments=json.dumps(arguments)))
        message = NS(content=None, reasoning=None, tool_calls=[tool])
        return NS(choices=[NS(message=message, finish_reason="tool_calls")], usage=None)
    client = NS(chat=NS(completions=NS(create=create)))
    monkeypatch.setattr("agent.process_bootstrap.OpenAI", lambda **kw: client)
    agent = AIAgent(model="test-model", api_key="test-key", base_url="http://localhost:9999/v1",
                    session_id="chat-1", platform="cli", enabled_toolsets=["project", "file"],
                    max_iterations=4, quiet_mode=True, skip_memory=True, skip_context_files=True,
                    save_trajectories=False)
    agent._disable_streaming = True
    result = agent.run_conversation("Φτιάξε ένα μικρό πρόγραμμα που αθροίζει αριθμούς.", task_id="chat-runtime")
    program = folder / "my-program" / "app.py"
    assert program.read_text(encoding="utf-8") == source
    execution = subprocess.run([sys.executable, str(program)], cwd=folder, text=True, capture_output=True, check=True)
    assert execution.stdout.strip() == "10"
    assert "my-program/app.py" in result["final_response"]
    assert not engine.tasks and not checks and not (folder / ".git").exists()
    assert len(requests) == 3
