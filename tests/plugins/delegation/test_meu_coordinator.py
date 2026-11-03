"""Real bundled discovery and delegate_task dispatch; no live inference or user data."""

import copy
import json

import pytest
import hermes_yaml as yaml



def task(workload="routine", paths=None, **extra):
    return {"goal": "Complete this concrete project deliverable", "workload": workload,
            "acceptance": "Run the relevant check and report the actual result",
            "parallel_safe": True, "write_paths": paths or [], **extra}


def dispatch(parent, tasks):
    from tools.registry import registry
    return json.loads(registry.dispatch("delegate_task", {"tasks": tasks, "background": False}, parent_agent=parent))


def test_semantic_plan_routes_short_complex_and_long_routine_work_independently(coordinator):
    _, built, parent = coordinator
    tasks = [task(goal="Extract the version fields " * 100), task("complex", ["src/api.py"], goal="Prove termination")]
    before = copy.deepcopy(tasks)
    out = dispatch(parent, tasks)
    assert "results" in out, out
    assert [r["status"] for r in out["results"]] == ["completed", "completed"]
    assert [b["model"] for b in built] == ["deepseek-flash", "deepseek-v4-pro"]
    assert all(b["override_provider"] == "deepseek" for b in built)
    assert "Acceptance checks:" in built[0]["context"]
    assert "Read-only" in built[0]["context"] and "src/api.py" in built[1]["context"]
    assert "routine" in out["results"][0]["route"]["label"]
    assert tasks == before


@pytest.mark.parametrize("paths", [(["src"], ["src/file.py"]), (["SRC/A.py"], ["src\\a.py"]), (["."], ["README.md"])])
def test_overlapping_parallel_writes_refuse_before_building_any_child(coordinator, paths):
    _, built, parent = coordinator
    out = dispatch(parent, [task(paths=paths[0]), task(paths=paths[1])])
    assert "overlapping write_paths" in out["error"]
    assert built == []


def test_dependent_tasks_wait_for_a_later_call(coordinator):
    _, built, parent = coordinator
    out = dispatch(parent, [task(), task("complex", parallel_safe=False)])
    assert "later call" in out["error"] and built == []
    out = dispatch(parent, [task("complex", parallel_safe=False, context="Prerequisite artifact: spec.md, reviewed")])
    assert out["results"][0]["status"] == "completed"
    assert "Prerequisite artifact" in built[0]["context"]


@pytest.mark.parametrize("patch", [{"acceptance": ""}, {"parallel_safe": "yes"}, {"write_paths": "src"},
                                  {"write_paths": ["../outside"]}, {"write_paths": ["C:\\private"]},
                                  {"write_paths": ["src/*.py"]}, {"workload": "cheap"}])
def test_incomplete_or_invalid_plans_do_not_start_workers(coordinator, patch):
    _, built, parent = coordinator
    out = dispatch(parent, [task(**patch)])
    assert "error" in out and built == []


def test_vision_task_routes_to_flash(coordinator):
    _, built, parent = coordinator
    out = dispatch(parent, [task("vision")])
    assert out["results"][0]["status"] == "completed"
    assert built[0]["model"] == "deepseek-flash"


def test_schema_is_stable_and_coordinator_is_discoverable_for_settings(coordinator):
    from agent.delegation_backends import list_backends
    from tools.registry import registry
    first = json.dumps(registry.get_definitions({"delegate_task"}), sort_keys=True)
    second = json.dumps(registry.get_definitions({"delegate_task"}), sort_keys=True)
    assert first == second and '"parallel_safe"' in first and '"acceptance"' in first
    entry = next(b for b in list_backends() if b.name == "meu_coordinator")
    assert entry.available and entry.label == "Meu Coordinator"


def test_another_profile_keeps_its_own_delegation_mode(coordinator, tmp_path, monkeypatch):
    from tools.delegate_tool_config import _load_config
    from tools.delegate_tool_routes import resolve_task_routes
    other = tmp_path / "other"
    other.mkdir()
    (other / "config.yaml").write_text(yaml.safe_dump({"delegation": {"backend": "default"}}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(other))
    routes, error = resolve_task_routes([{"goal": "A task with no coordinator fields"}], _load_config(), coordinator[2])
    assert error is None and routes[0].backend == "default" and routes[0].creds["model"] is None


def test_real_child_requests_keep_planned_models_and_never_contact_nous(coordinator, monkeypatch):
    import httpx
    from tools import delegate_tool as dt

    _, _, parent = coordinator
    parent.enabled_toolsets = []
    parent.disabled_toolsets = []
    monkeypatch.setattr(dt, "_build_child_preserving_parent_tools", parent._test_original_build)
    monkeypatch.setattr(dt, "_run_single_child", parent._test_original_run)
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append((request.url.host, body))
        assert request.url.host == "api.deepseek.com"
        text = "Checked the assigned deliverable; no project files were changed."
        if body.get("stream"):
            chunk = {"id": "mock", "object": "chat.completion.chunk", "created": 0, "model": body["model"],
                     "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": "stop"}]}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={"id": "mock", "object": "chat.completion", "created": 0,
                                        "model": body["model"], "choices": [{"index": 0,
                                        "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    monkeypatch.setattr("agent.process_bootstrap.build_keepalive_http_client",
                        lambda *a, **kw: httpx.Client(transport=httpx.MockTransport(respond)))
    out = dispatch(parent, [task(goal="Implement a trivial mechanical rename"), task("complex", goal="Prove termination")])
    assert "results" in out, out
    assert [entry["status"] for entry in out["results"]] == ["completed", "completed"], out
    assert {body["model"] for _, body in requests} == {"deepseek-flash", "deepseek-v4-pro"}
    assert len(requests) == 2
    for _, body in requests:
        text = json.dumps(body["messages"])
        assert "Coordinator task contract" in text and "Acceptance checks:" in text
