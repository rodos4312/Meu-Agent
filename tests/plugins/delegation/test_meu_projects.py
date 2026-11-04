"""Persistent projects use the actual plugin registry and native delegation path."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.plugins.delegation.test_meu_coordinator import task

pytestmark = pytest.mark.usefixtures("coordinator")


def project(parent, action, **values):
    from model_tools import handle_function_call
    return json.loads(handle_function_call("coordinate_project", {"action": action, "project": "demo", **values}, parent_agent=parent))


def create(parent, root, tasks=None):
    result = project(parent, "create", root=str(root), tasks=tasks or [
        task(id="inspect"), task("complex", ["answer.txt"], id="implement", depends_on=["inspect"])])
    return result


def test_project_waits_for_verification_resumes_and_uses_both_models(coordinator, tmp_path):
    home, built, parent = coordinator
    parent.session_id = "project-session"
    created = create(parent, tmp_path)
    assert "ready" in created, created
    assert created["ready"] == ["inspect"]
    first = project(parent, "run")
    assert first["tasks"]["inspect"]["state"] == "needs_review"
    assert first["ready"] == [] and not first["complete"]
    project(parent, "run")
    assert len(built) == 1  # completed-but-unverified work never repeats
    result = project(parent, "verify", task="inspect", attempt=1, passed=True, evidence="Inspected source and reproduced the issue.")
    assert result["ready"] == ["implement"]
    second = project(parent, "run")
    assert second["tasks"]["implement"]["state"] == "needs_review"
    assert [child["model"] for child in built] == ["deepseek-flash", "deepseek-v4-pro"]
    assert "Verified prerequisite results" in built[1]["context"]
    (tmp_path / "answer.txt").write_text("tested output", encoding="utf-8")
    assert "artifact" in project(parent, "verify", task="implement", attempt=1, passed=True, evidence="Tests passed.")["error"]
    verified = project(parent, "verify", task="implement", attempt=1, passed=True, evidence="Ran acceptance checks: passed.", artifacts=["answer.txt"])
    assert verified["complete"]
    # A fresh process reads the persisted outcome without the original parent or manager.
    script = "from pathlib import Path;from plugins.delegation.meu_coordinator.projects import open_project;" \
        f"\nwith open_project(Path({str(home)!r}),'demo') as p:" \
        "\n assert p.summary()['complete'] and p.record['session_id'] == 'project-session'"
    subprocess.run([sys.executable, "-c", script], check=True, timeout=30,
                   cwd=Path(__file__).resolve().parents[3])


def test_project_tool_reaches_the_actual_model_schema_with_delegation_enabled(coordinator):
    from model_tools import get_tool_definitions
    from toolsets import resolve_toolset
    assert "coordinate_project" in resolve_toolset("delegation")
    definitions = get_tool_definitions(enabled_toolsets=["delegation"], quiet_mode=True,
                                       skip_tool_search_assembly=True)
    project_schema = next(item["function"] for item in definitions if item["function"]["name"] == "coordinate_project")
    assert project_schema["parameters"]["required"] == ["action", "project"]


def test_normal_agent_executor_passes_parent_to_project_handler(coordinator, tmp_path):
    from agent.tool_executor import _ToolCallRef, _resolve_sequential_dispatch
    from agent.tool_dispatch_helpers import _extend_tool_timeout
    _, _, parent = coordinator
    parent._context_engine_tool_names = set()
    parent._memory_manager = None
    parent.quiet_mode = False
    parent.valid_tool_names = {"coordinate_project"}
    parent.enabled_toolsets = ["delegation"]
    parent.disabled_toolsets = []
    args = {"action": "create", "project": "demo", "root": str(tmp_path), "tasks": [task(id="inspect")]}
    dispatch = _resolve_sequential_dispatch(parent, _ToolCallRef("coordinate_project", args, "test", "call", []), [])
    result = json.loads(dispatch.execute(args))
    assert result.get("ready") == ["inspect"], result
    assert _extend_tool_timeout("coordinate_project", 120) == 3600


def test_interrupted_work_requires_reconciliation_and_explicit_bounded_retry(coordinator, tmp_path):
    home, built, parent = coordinator
    create(parent, tmp_path, [task(id="extract")])
    file = home / "coordinator" / "demo.json"
    record = json.loads(file.read_text(encoding="utf-8-sig"))
    record["tasks"]["extract"].update(state="running", attempt=1)
    file.write_text(json.dumps(record), encoding="utf-8")
    assert project(parent, "status")["tasks"]["extract"]["state"] == "interrupted"
    project(parent, "run")
    assert built == []
    assert "evidence" in project(parent, "retry", task="extract", attempt=1)["error"]
    project(parent, "retry", task="extract", attempt=1, evidence="Existing output inspected; no external side effect; finish the missing portion.")
    result = project(parent, "run")
    assert built[0]["model"] == "deepseek-v4-pro"
    assert result["tasks"]["extract"]["attempt"] == 2
    assert "exact task attempt" in project(parent, "verify", task="extract", attempt=1, passed=True, evidence="stale")["error"]


def test_safe_parallel_selection_never_overlaps_declared_writes(coordinator, tmp_path):
    _, built, parent = coordinator
    create(parent, tmp_path, [task(paths=["src"], id="one"), task(paths=["src/file.py"], id="two"), task(id="read")])
    result = project(parent, "run")
    assert result["tasks"]["two"]["state"] == "pending"
    assert len(built) == 2


def test_changed_artifact_invalidates_verified_downstream_results(coordinator, tmp_path):
    _, _, parent = coordinator
    create(parent, tmp_path, [task(paths=["spec.txt"], id="inspect"), task(id="implement", depends_on=["inspect"])])
    (tmp_path / "spec.txt").write_text("version 1", encoding="utf-8")
    project(parent, "run")
    project(parent, "verify", task="inspect", attempt=1, passed=True, evidence="Spec checked.", artifacts=["spec.txt"])
    project(parent, "run")
    assert project(parent, "verify", task="implement", attempt=1, passed=True, evidence="Output checked.")["complete"]
    (tmp_path / "spec.txt").write_text("version 2", encoding="utf-8")
    result = project(parent, "status")
    assert not result["complete"]
    assert all(row["state"] == "needs_review" for row in result["tasks"].values())


def test_project_lock_and_profile_boundaries_preserve_other_work(coordinator, tmp_path):
    from plugins.delegation.meu_coordinator.projects import open_project
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    home, _, parent = coordinator
    create(parent, tmp_path)
    with open_project(home, "demo"):
        assert "already running" in project(parent, "run")["error"]
    other = tmp_path / "other-profile"
    other.mkdir()
    (other / "config.yaml").write_text("delegation:\n  backend: meu_coordinator\n", encoding="utf-8")
    token = set_hermes_home_override(other)
    try:
        assert "error" in project(parent, "status")
    finally:
        reset_hermes_home_override(token)
    assert project(parent, "status")["ready"] == ["inspect"]


def test_rejects_missing_artifacts_and_limits_failed_retries(coordinator, tmp_path):
    _, built, parent = coordinator
    create(parent, tmp_path, [task(paths=["answer.txt"], id="write")])
    for attempt in range(1, 4):
        project(parent, "run")
        assert "error" in project(parent, "verify", task="write", attempt=attempt, passed=True,
                                  evidence="Checked.", artifacts=["../outside.txt"])
        rejected = project(parent, "verify", task="write", attempt=attempt, passed=False,
                           evidence="Acceptance test failed: output is missing.")
        assert rejected["tasks"]["write"]["state"] == "failed"
        retry = project(parent, "retry", task="write", attempt=attempt,
                        evidence="Inspected existing output; repair the missing file only.")
        assert ("error" in retry) == (attempt == 3)
    assert len(built) == 3
    assert built[1]["model"] == "deepseek-v4-pro"


def test_parent_database_selects_the_owning_profile_even_when_ambient_home_differs(coordinator, tmp_path):
    from types import SimpleNamespace
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from plugins.delegation.meu_coordinator.project_tool import handle
    home, _, parent = coordinator
    parent._session_db = SimpleNamespace(db_path=str(home / "state.db"))
    parent._delegation_backend = "meu_coordinator"
    token = set_hermes_home_override(tmp_path / "ambient")
    try:
        # The registry already selected this handler before the context was lost.
        result = json.loads(handle({"action": "create", "project": "demo", "root": str(tmp_path),
                                    "tasks": [task(id="inspect")]}, parent_agent=parent))
        assert result.get("project") == "demo", result
    finally:
        reset_hermes_home_override(token)
    assert (home / "coordinator" / "demo.json").is_file()
    assert not (tmp_path / "ambient" / "coordinator" / "demo.json").exists()


@pytest.mark.parametrize("tasks", [[task(id="a", depends_on=["missing"])],
                                    [task(id="a", depends_on=["b"]), task(id="b", depends_on=["a"])],
                                    [task(id="same"), task(id="same")]])
def test_invalid_graph_never_creates_project_or_children(coordinator, tmp_path, tasks):
    home, built, parent = coordinator
    assert "error" in create(parent, tmp_path, tasks)
    assert not (home / "coordinator" / "demo.json").exists()
    assert not built
