"""Real async registry, project checkpoints and profile files; inference is deterministic."""
import json
from threading import Event
from types import SimpleNamespace

import pytest
import hermes_yaml as yaml

from tests.plugins.delegation.test_meu_coordinator import task
from tests.plugins.delegation.test_meu_projects import create, project
from tests.waiting import wait_until


@pytest.fixture
def interactive(coordinator, monkeypatch):
    from tools import async_delegation as ad, delegate_tool as dt, delegate_tool_dispatch as dispatch
    from tools.registry import registry
    ad._reset_for_tests()
    home, built, parent = coordinator
    config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    config["delegation"]["independent_completions"] = True
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    parent.tools = [{"type": "function", "function": registry.get_definitions({"delegate_task"})[0]["function"]}]
    parent._session_db = SimpleNamespace(db_path=str(home / "state.db"))
    monkeypatch.setattr(dispatch, "_resolve_async_wake_sid", lambda *a, **kw: "")
    gates = [Event(), Event()]
    entered = [Event(), Event()]
    original = dt._run_single_child

    def run(task_index, goal, child, **kwargs):
        index = task_index
        entered[index].set()
        assert gates[index].wait(10), "test must release the helper"
        return original(task_index=task_index, goal=goal, child=child, **kwargs)

    monkeypatch.setattr(dt, "_run_single_child", run)
    try:
        yield home, built, parent, entered, gates
    finally:
        for gate in gates:
            gate.set()
        wait_until(lambda: ad.active_count() == 0, what="async workers settled before fixture teardown")
        ad._reset_for_tests()


def test_background_project_returns_live_status_checkpoints_and_preserves_review(interactive, tmp_path):
    from tools import async_delegation as ad
    home, built, parent, entered, gates = interactive
    create(parent, tmp_path, [task(id="one"), task("complex", id="two")])
    started = project(parent, "run")
    assert started.get("dispatch", {}).get("status") == "dispatched", started
    assert all(event.wait(5) for event in entered)
    assert project(parent, "status")["tasks"]["two"]["state"] == "running"
    assert "already running" in project(parent, "run")["error"]
    assert len(built) == 2
    gates[0].set()

    def partial():
        saved = json.loads((home / "coordinator/demo.json").read_text(encoding="utf-8"))
        return saved if saved["tasks"]["one"]["state"] == "needs_review" else None

    partial_state = wait_until(partial, what="first helper checkpointed before the second finishes")
    assert partial_state["tasks"]["two"]["state"] == "running"
    unit = started["dispatch"]["delegation_id"]
    durable = wait_until(lambda: (ad.get_durable_delegation(unit) or {}).get("result"), what="native partial receipt")
    assert durable["results"][0]["task_index"] == 0
    # Another chat/turn stopping does not stop this detached project batch.
    parent._interrupt_requested = True
    gates[1].set()
    wait_until(lambda: ad.active_count() == 0, what="project background completion")
    finished = project(parent, "status")
    assert all(row["state"] == "needs_review" for row in finished["tasks"].values())
    assert not finished["complete"]
    assert [item["model"] for item in built] == ["deepseek-flash", "deepseek-v4-pro"]
    assert all(item["override_provider"] is None for item in built)
    project(parent, "run")
    assert len(built) == 2


def test_refused_background_spawn_releases_project_and_records_failure(interactive, monkeypatch, tmp_path):
    from tools import delegate_tool as dt
    _, built, parent, _, _ = interactive
    create(parent, tmp_path, [task(id="one")])
    monkeypatch.setattr(dt, "is_spawn_paused", lambda: True)
    result = project(parent, "run")
    assert result["tasks"]["one"]["state"] == "failed", result
    assert not built
    assert project(parent, "status")["tasks"]["one"]["state"] == "failed"


def test_background_host_failure_releases_lock_without_claiming_success(interactive, monkeypatch, tmp_path):
    from tools import async_delegation as ad, delegate_tool_dispatch as dispatch
    _, _, parent, _, gates = interactive
    create(parent, tmp_path, [task(id="one")])

    def fail(*args, **kwargs):
        assert gates[0].wait(10)
        raise RuntimeError("controlled host failure")

    monkeypatch.setattr(dispatch, "_finalize_child_results", fail)
    started = project(parent, "run")
    assert started.get("dispatch", {}).get("status") == "dispatched", started
    gates[0].set()
    wait_until(lambda: ad.active_count() == 0, what="failed unit settled")
    status = project(parent, "status")
    assert status["tasks"]["one"]["state"] == "needs_review", status
    assert not status["complete"]


def test_partial_refusal_is_checkpointed_before_a_fast_batch_releases_its_lock(interactive, monkeypatch, tmp_path):
    from dataclasses import replace
    from tools import async_delegation as ad, delegate_tool as dt, delegate_tool_dispatch as dispatch
    _, built, parent, _, gates = interactive
    create(parent, tmp_path, [task(id="one"), task("complex", id="two")])
    route = dt._routes_for
    background = dispatch._dispatch_background

    def refuse(*args, **kwargs):
        routes, error = route(*args, **kwargs)
        return [routes[0], replace(routes[1], error="controlled model refusal")], error

    def finish_before_return(batch):
        answer = background(batch)
        wait_until(lambda: ad.active_count() == 0, what="worker finished before dispatch returns")
        return answer

    monkeypatch.setattr(dt, "_routes_for", refuse)
    monkeypatch.setattr(dispatch, "_dispatch_background", finish_before_return)
    gates[0].set()
    result = project(parent, "run")
    assert len(built) == 1
    assert result["tasks"]["one"]["state"] == "needs_review"
    assert result["tasks"]["two"]["state"] == "failed"
    assert result["tasks"]["two"]["result"]["error"] == "controlled model refusal"
    assert project(parent, "status")["tasks"] == result["tasks"]


def test_explicit_session_stop_settles_background_project(interactive, monkeypatch, tmp_path):
    from tools import async_delegation as ad, delegate_tool as dt
    _, _, parent, entered, gates = interactive
    stopped = Event()
    build = dt._build_child_preserving_parent_tools

    def make_child(**kwargs):
        child = build(**kwargs)

        def stop(*args, **kw):
            stopped.set()
            gates[0].set()

        child.hard_interrupt = stop
        return child

    def run_child(task_index, **kwargs):
        entered[0].set()
        assert stopped.wait(10), "explicit stop must reach the native child"
        return {"task_index": task_index, "status": "interrupted", "summary": "Stopped by the user."}

    monkeypatch.setattr(dt, "_build_child_preserving_parent_tools", make_child)
    monkeypatch.setattr(dt, "_run_single_child", run_child)
    create(parent, tmp_path, [task(id="one")])
    assert project(parent, "run")["dispatch"]["status"] == "dispatched"
    assert entered[0].wait(5)
    assert ad.interrupt_for_session(parent_session_id=parent.session_id) == 1
    wait_until(lambda: ad.active_count() == 0, what="explicitly stopped project settles")
    status = project(parent, "status")
    assert status["tasks"]["one"]["state"] == "interrupted"
    assert status["tasks"]["one"]["result"]["summary"] == "Stopped by the user."


def test_profile_switch_does_not_move_a_background_checkpoint(interactive, tmp_path):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from plugins.delegation.meu_coordinator.project_tool import handle
    from tools import async_delegation as ad
    home, _, parent, entered, gates = interactive
    parent._delegation_backend = "meu_coordinator"
    create(parent, tmp_path, [task(id="one")])
    assert project(parent, "run")["dispatch"]["status"] == "dispatched"
    assert entered[0].wait(5)
    other = tmp_path / "other-profile"
    other.mkdir()
    token = set_hermes_home_override(other)
    try:
        gates[0].set()
        wait_until(lambda: ad.active_count() == 0, what="original profile's worker finishes")
        status = json.loads(handle({"project": "demo", "action": "status"}, parent_agent=parent))
        assert status["tasks"]["one"]["state"] == "needs_review", status
        assert (home / "coordinator/demo.json").is_file()
        assert not (other / "coordinator").exists()
    finally:
        reset_hermes_home_override(token)
