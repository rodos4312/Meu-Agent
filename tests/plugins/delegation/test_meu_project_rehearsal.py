"""Rehearse a real file project through native delegation across process death."""

import csv
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import traceback
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from tests.plugins.delegation.test_meu_coordinator import task
from tests.plugins.delegation.test_meu_projects import create, project
from tests.waiting import wait_until

REPO = Path(__file__).resolve().parents[3]
INTERRUPTED = 79


def _local_socket(connect):
    def guarded(sock, address):
        # Windows asyncio uses a loopback socket pair for its own wakeups.
        if address[0] not in {"127.0.0.1", "::1"}:
            raise AssertionError("The coordinator rehearsal cannot open external sockets.")
        return connect(sock, address)
    return guarded


def _read(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def _verify(parent, name, attempt, artifact, evidence):
    return project(parent, "verify", task=name, attempt=attempt, passed=True,
                   artifacts=[artifact], evidence=evidence)


def _start(root, parent):
    from tools.memory_tool import load_on_disk_store

    memory = load_on_disk_store(project_cwd=str(root))
    assert memory.add("project", "Normalization retains duplicate payment rows.")["success"]
    assert memory.add("project", "Reports subtract refunds from receipts.")["success"]
    plan = [
        task(id="normalize", paths=["rows.json"], tool_access="files_only",
             goal="Normalize the payments CSV to JSON."),
        task("complex", ["report.json"], id="reconcile", depends_on=["normalize"],
             tool_access="files_only", goal="Deduplicate payment IDs, apply refunds, and write the reconciliation report."),
    ]
    initial = create(parent, root, plan)
    assert initial["ready"] == ["normalize"]
    notes = {note["content"]: note["id"] for note in initial["memory_notes"]}
    result = project(parent, "run", task_memory={"normalize": [notes["Normalization retains duplicate payment rows."]]})
    assert result["tasks"]["normalize"]["state"] == "needs_review", result
    _assert_blocked_terminal(result["tasks"]["normalize"]["result"])
    assert not (root.parent / "outside.json").exists()
    assert not (root / "undeclared.json").exists()
    assert result["ready"] == []
    with (root / "payments.csv").open(encoding="utf-8", newline="") as source:
        expected = [{"id": row["id"], "cents": int(row["cents"])} for row in csv.DictReader(source)]
    assert _read(root, "rows.json") == expected
    assert _verify(parent, "normalize", 1, "rows.json", "Compared all rows to the CSV.")["ready"] == ["reconcile"]
    project(parent, "run", task_memory={"reconcile": [notes["Reports subtract refunds from receipts."]]})
    raise AssertionError("The process should have exited after the report write.")


def _resume(root, parent, requests):
    status = project(parent, "status")
    assert status["tasks"]["reconcile"]["task"]["tool_access"] == "files_only"
    assert status["tasks"]["normalize"]["state"] == "verified"
    assert status["tasks"]["normalize"]["attempt"] == 1
    assert status["tasks"]["reconcile"]["state"] == "interrupted"
    assert status["tasks"]["reconcile"]["attempt"] == 1
    assert not project(parent, "run")["complete"]
    assert requests == []
    assert _read(root, "report.json") == {"net_cents": 1700}
    from tools.memory_tool import load_on_disk_store
    from tui_gateway.project_memory import snapshot, update

    memory = load_on_disk_store(project_cwd=str(root))
    before = snapshot(memory)
    original = next(note for note in before["entries"] if note["content"].startswith("Reports"))
    edited = update(memory, {"action": "patch", "revision": before["revision"], "note_id": original["id"],
                             "content": "Reports subtract refunds and remove duplicate payment IDs."})
    assert edited["saved"]
    current = next(note for note in edited["memory"]["entries"] if note["content"].startswith("Reports"))
    retry = project(parent, "retry", task="reconcile", attempt=1,
                    evidence="Existing report has the wrong total and can be regenerated locally.")
    assert retry["ready"] == ["reconcile"]
    result = project(parent, "run", task_memory={"reconcile": [current["id"]]})
    assert result["tasks"]["reconcile"]["state"] == "needs_review", result
    _assert_blocked_terminal(result["tasks"]["reconcile"]["result"])
    assert "error" not in result["tasks"]["reconcile"]
    assert requests == ["deepseek-v4-pro"] * 3
    assert _read(root, "report.json") == {"net_cents": 700, "unique_payments": 2}
    assert "exact task attempt" in _verify(parent, "reconcile", 1, "report.json", "Stale review.")["error"]
    unrelated = _verify(parent, "reconcile", 2, "payments.csv", "Checked the original input.")
    assert "artifact" in unrelated.get("error", ""), unrelated
    verified = _verify(parent, "reconcile", 2, "report.json", "1000 cents minus 300; duplicate excluded.")
    assert not verified["complete"]
    for expected_stage in ("requirements", "quality"):
        assert len(verified["ready"]) == 1
        key = verified["ready"][0]
        assert verified["tasks"][key]["task"]["review_stage"] == expected_stage
        project(parent, "run")
        verified = project(parent, "verify", task=key, attempt=1, passed=True,
                           evidence="Confirmed the reviewer read the current report and its reproduced totals.")
    assert verified["complete"], verified
    assert requests == ["deepseek-v4-pro"] * 7


def _assert_blocked_terminal(result):
    assert any(call["tool"] == "terminal" and call["status"] == "error" for call in result["tool_trace"]), result


def _build_and_probe_scoped_child(build, **kwargs):
    from agent.tool_executor import _run_agent_tool_execution_middleware
    from tools.mcp_tool_agent import refresh_agent_mcp_tools

    child = build(**kwargs)
    refresh_agent_mcp_tools(child, enabled_override=["file", "terminal", "code_execution"])
    assert child.valid_tool_names == {"read_file", "write_file", "patch", "search_files"}

    def unexpected_dispatch(_args):
        raise AssertionError("The terminal handler must never run.")

    outcome = _run_agent_tool_execution_middleware(
        child, function_name="terminal", function_args={"command": "echo denied"},
        effective_task_id="scope-probe", tool_call_id="scope-probe", execute=unexpected_dispatch,
    )
    assert outcome.blocked and "delegation tool scope" in json.loads(outcome.result)["error"]
    return child


def _response(request, root, stage, requests):
    assert request.url.host == "api.deepseek.com"
    body = json.loads(request.content)
    assert {entry["function"]["name"] for entry in body["tools"]} == {"read_file", "write_file", "patch", "search_files"}
    model = body["model"]
    context = json.dumps(body["messages"])
    if "Review stage: " in context:
        requests.append(model)
        assert model == "deepseek-v4-pro" and stage == "resume"
        return _review_response(body, root)
    if model == "deepseek-flash":
        assert "Normalization retains duplicate" in context and "Reports subtract" not in context
    else:
        assert "Reports subtract refunds" in context
        assert "Normalization retains duplicate" not in context
        if stage == "resume":
            assert "remove duplicate payment IDs" in context
    requests.append(model)
    expected = ["deepseek-flash"] * 2 + ["deepseek-v4-pro"] * 2 if stage == "start" else ["deepseek-v4-pro"] * 3
    assert requests == expected[:len(requests)], requests
    if model == "deepseek-flash":
        name = "rows.json"
        output = [{"id": "p1", "cents": 1000}, {"id": "p1", "cents": 1000}, {"id": "r1", "cents": -300}]
    else:
        messages = json.dumps(body["messages"])
        assert "Verified prerequisite results" in messages and "Wrote rows.json." in messages
        name = "report.json"
        output = {"net_cents": 1700} if stage == "start" else {"net_cents": 700, "unique_payments": 2}
    message = {"content": f"Wrote {name}."}
    finish = "stop"
    final_request = len(requests) in ({2, 4} if stage == "start" else {3})
    if final_request:
        last = body["messages"][-1]
        assert last["role"] == "tool" and _read(root, name) == output, last
        assert any(msg.get("tool_call_id") == "call_terminal" and "delegation tool scope" in msg["content"]
                   for msg in body["messages"] if msg["role"] == "tool")
        if model == "deepseek-flash":
            denied = {msg.get("tool_call_id") for msg in body["messages"]
                      if msg["role"] == "tool" and "project file scope" in msg["content"]}
            assert denied == {"call_outside", "call_undeclared", "call_move", "call_link", "call_search"}
            broad = next(msg["content"] for msg in body["messages"] if msg.get("tool_call_id") == "call_broad_search")
            assert "decoy.txt" not in broad and not json.loads(broad).get("error"), broad
        if stage == "start" and model == "deepseek-v4-pro":
            os._exit(INTERRUPTED)
    else:
        arguments = {"path": name}
        if stage == "start":
            tool = "write_file"
            arguments["content"] = json.dumps(output)
        elif len(requests) == 1:
            tool = "read_file"
        else:
            tool = "patch"
            arguments.update(old_string=json.dumps({"net_cents": 1700}), new_string=json.dumps(output))
        assert tool in {entry["function"]["name"] for entry in body["tools"]}
        call = {"id": f"call_{tool}", "type": "function",
                "function": {"name": tool, "arguments": json.dumps(arguments)}}
        calls = [call]
        if tool != "read_file":
            calls.insert(0, {"id": "call_terminal", "type": "function",
                             "function": {"name": "terminal", "arguments": '{"command":"echo denied"}'}})
        if model == "deepseek-flash":
            for call_id, function, args in (
                ("call_outside", "write_file", {"path": str(root.parent / "outside.json"), "content": "outside"}),
                ("call_undeclared", "write_file", {"path": "undeclared.json", "content": "outside write scope"}),
                ("call_move", "patch", {"mode": "patch", "patch": "*** Begin Patch\n*** Move File: rows.json -> undeclared.json\n*** End Patch"}),
                ("call_link", "read_file", {"path": "linked/decoy.txt"}),
                ("call_search", "search_files", {"path": "linked", "pattern": "outside"}),
                ("call_broad_search", "search_files", {"path": ".", "pattern": "outside"}),
            ):
                calls.insert(0, {"id": call_id, "type": "function",
                                 "function": {"name": function, "arguments": json.dumps(args)}})
        if body.get("stream"):
            for index, call in enumerate(calls):
                call["index"] = index
        message = {"content": None, "tool_calls": calls}
        finish = "tool_calls"
    return _provider_response(body, message, finish)


def _review_response(body, root):
    tool_results = {message.get("tool_call_id"): message for message in body["messages"] if message["role"] == "tool"}
    if "review_read" not in tool_results:
        calls = [
            {"id": "review_read", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": "report.json"})}},
            {"id": "review_write", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "report.json", "content": "forbidden"})}},
        ]
        if body.get("stream"):
            for index, call in enumerate(calls):
                call["index"] = index
        return _provider_response(body, {"content": None, "tool_calls": calls}, "tool_calls")
    assert "700" in tool_results["review_read"]["content"]
    assert "project file scope" in tool_results["review_write"]["content"]
    assert _read(root, "report.json") == {"net_cents": 700, "unique_payments": 2}
    finding = {"verdict": "pass", "check": "Read report.json and compare duplicate/refund totals.",
               "observed": "The report retains two unique payments and net 700 cents; review writes were refused."}
    return _provider_response(body, {"content": json.dumps(finding)}, "stop")


def _provider_response(body, message, finish):
    response = {"id": "rehearsal", "created": 0, "model": body["model"]}
    choice = {"index": 0, "finish_reason": finish}
    if body.get("stream"):
        response.update(object="chat.completion.chunk", choices=[{**choice, "delta": message}])
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=f"data: {json.dumps(response)}\n\ndata: [DONE]\n\n")
    response.update(object="chat.completion", choices=[{**choice, "message": {"role": "assistant", **message}}])
    return httpx.Response(200, json=response)


def _parallel_response(request, workspace):
    assert request.url.host == "api.deepseek.com"
    body = json.loads(request.content)
    if body["model"] == "deepseek-v4-pro":
        def finished_record():
            record = _read(workspace / "home" / "coordinator", "demo.json")
            return record if record["tasks"]["finished"]["state"] == "needs_review" else None

        record = wait_until(finished_record, timeout=30, interval=0.1, what="the finished sibling's checkpoint")
        assert record["tasks"]["slow"]["state"] == "running"
        os._exit(INTERRUPTED)
    message = {"content": "Finished the independent inspection."}
    choice = {"index": 0, "finish_reason": "stop"}
    response = {"id": "parallel", "created": 0, "model": body["model"]}
    if body.get("stream"):
        response.update(object="chat.completion.chunk", choices=[{**choice, "delta": message}])
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=f"data: {json.dumps(response)}\n\ndata: [DONE]\n\n")
    response.update(object="chat.completion", choices=[{**choice, "message": {"role": "assistant", **message}}])
    return httpx.Response(200, json=response)


def _start_parallel(root, parent, *, background=False):
    plan = [task(id="finished", paths=[], tool_access="files_only"),
            task("complex", [], id="slow", tool_access="files_only")]
    assert create(parent, root, plan)["ready"] == ["finished", "slow"]
    result = project(parent, "run")
    if background:
        assert result.get("dispatch", {}).get("status") == "dispatched", result
        from tools.async_delegation import active_count
        wait_until(lambda: active_count() == 0, timeout=30, what="controlled background process interruption")
    raise AssertionError("The second worker should have stopped the process.")


def _resume_parallel(parent, requests):
    status = project(parent, "status")
    assert status["tasks"]["finished"]["state"] == "needs_review"
    assert status["tasks"]["finished"]["result"]["summary"] == "Finished the independent inspection."
    assert status["tasks"]["slow"]["state"] == "interrupted"
    assert status["ready"] == [] and requests == []


def _missing_worktree(root, parent, requests):
    plan = [task(id="isolated", paths=["rows.json"], tool_access="files_only")]
    assert create(parent, root, plan)["ready"] == ["isolated"]
    row = project(parent, "run")["tasks"]["isolated"]
    assert row["state"] == "failed" and requests == [], row
    assert "Could not prepare the requested project worktree" in row["result"]["error"], row
    assert not (root / "rows.json").exists()


def _rehearse(workspace, stage):
    from hermes_cli.plugins import PluginManager
    from model_tools import get_tool_definitions
    from tools import delegate_tool
    from tools.terminal_tool import record_session_cwd

    requests = []
    mode = stage.removeprefix("background-")
    root = workspace / "project"
    parent = SimpleNamespace(session_id="rehearsal-parent", provider="deepseek", model="deepseek-v4-pro",
                             base_url="https://api.deepseek.com/v1", api_key="meu-test-only", request_overrides={},
                             cwd=str(workspace), _current_task_id="rehearsal-parent",
                             tool_progress_callback=None, _delegate_spinner=None,
                             _safe_print=lambda line: None,
                             enabled_toolsets=["file", "terminal", "code_execution", "delegation"], disabled_toolsets=[])
    def respond(request):
        try:
            if mode == "parallel":
                return _parallel_response(request, workspace)
            return _response(request, root, stage, requests)
        except Exception:
            traceback.print_exc()
            return httpx.Response(400, json={"error": {"message": "Rehearsal fixture assertion failed."}})

    transport = httpx.MockTransport(respond)
    build = delegate_tool._build_child_preserving_parent_tools
    with (
        patch("hermes_cli.plugins.get_bundled_plugins_dir", return_value=workspace / "bundled"),
        patch("agent.process_bootstrap.build_keepalive_http_client",
              side_effect=lambda *args, **kwargs: httpx.Client(transport=transport)),
        patch.object(delegate_tool, "_build_child_preserving_parent_tools",
                     side_effect=lambda **kwargs: _build_and_probe_scoped_child(build, **kwargs)),
        patch("tools.delegate_tool_dispatch._resolve_async_wake_sid",
              return_value="" if stage.startswith("background-") else None),
    ):
        manager = PluginManager()
        manager.discover_and_load()
        try:
            record_session_cwd(parent._current_task_id, str(workspace))
            parent.tools = get_tool_definitions(enabled_toolsets=parent.enabled_toolsets, quiet_mode=True,
                                                skip_tool_search_assembly=True)
            stages = {
                "start": (_start, (root, parent)),
                "resume": (_resume, (root, parent, requests)),
                "parallel": (_start_parallel, (root, parent)),
                "parallel-resume": (_resume_parallel, (parent, requests)),
                "background-parallel": (_start_background_parallel, (root, parent)),
                "background-parallel-resume": (_resume_parallel, (parent, requests)),
                "missing-worktree": (_missing_worktree, (root, parent, requests)),
            }
            run, args = stages[stage]
            run(*args)
        finally:
            manager.unload()


def _run_stages(tmp_path, stages, *, worktree=False):
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        f"delegation:\n  backend: meu_coordinator\n  worktree_isolation: {str(worktree).lower()}\n"
        "terminal:\n  backend: local\n", encoding="utf-8")
    shutil.copytree(REPO / "plugins" / "delegation", tmp_path / "bundled" / "delegation",
                    ignore=shutil.ignore_patterns("__pycache__"))
    env = {**os.environ, "HERMES_HOME": str(home), "MEU_HOME": str(home), "MEU_AGENT_MODE": "1",
           "DEEPSEEK_API_KEY": "meu-test-only", "PYTHONIOENCODING": "utf-8"}
    for stage, expected in stages:
        log = tmp_path / f"{stage}.log"
        with log.open("wb") as output:
            result = subprocess.run([sys.executable, "-m", "tests.plugins.delegation.test_meu_project_rehearsal",
                                     str(tmp_path), stage], cwd=REPO, env=env,
                                    stdout=output, stderr=subprocess.STDOUT, timeout=120, check=False)
        assert result.returncode == expected, log.read_text(encoding="utf-8", errors="replace")


def test_native_coordinator_recovers_a_real_file_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "payments.csv").write_text("id,cents\np1,1000\np1,1000\nr1,-300\n", encoding="utf-8")
    (tmp_path / "decoy.txt").write_text("outside", encoding="utf-8")
    linked = root / "linked"
    if os.name == "nt":
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(tmp_path)],
                       check=True, capture_output=True)
    else:
        linked.symlink_to(tmp_path, target_is_directory=True)
    _run_stages(tmp_path, (("start", INTERRUPTED), ("resume", 0)))
    home = tmp_path / "home"
    assert _read(home / "coordinator", "demo.json")["tasks"]["reconcile"]["state"] == "verified"


def test_finished_sibling_is_saved_before_parallel_batch_joins(tmp_path):
    _run_stages(tmp_path, (("parallel", INTERRUPTED), ("parallel-resume", 0)))


def _start_background_parallel(root, parent):
    _start_parallel(root, parent, background=True)


def test_background_project_recovers_finished_work_after_process_death(tmp_path):
    _run_stages(tmp_path, (("background-parallel", INTERRUPTED), ("background-parallel-resume", 0)))


def test_requested_worktree_failure_does_not_start_in_shared_project(tmp_path):
    _run_stages(tmp_path, (("missing-worktree", 0),), worktree=True)


if __name__ == "__main__":
    with (
        patch.object(socket.socket, "connect", _local_socket(socket.socket.connect)),
        patch.object(socket.socket, "connect_ex", _local_socket(socket.socket.connect_ex)),
    ):
        _rehearse(Path(sys.argv[1]), sys.argv[2])
