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
    assert all(b["override_provider"] is None for b in built)
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


@pytest.mark.parametrize("catalog_kind", [
    "verified", "curated", "other-account", "different-endpoint", "missing", "anthropic",
])
def test_coordinator_keeps_parent_transport_and_uses_its_discovered_catalog(coordinator, monkeypatch, catalog_kind):
    from hermes_cli import models
    from tools.delegate_tool_config import _resolve_child_runtime

    home, built, parent = coordinator
    parent.provider = "openai-codex"
    parent.model = "gpt-6.1-sol"
    parent.base_url = ("https://example.invalid/codex" if catalog_kind == "different-endpoint"
                       else "https://chatgpt.com/backend-api/codex")
    parent.api_mode = "codex_responses"
    parent._fallback_chain = [{"provider": "deepseek", "model": "deepseek-v4-pro"}]
    if catalog_kind == "anthropic":
        parent.provider = "anthropic"
        parent.model = "claude-sonnet-4-6"
        parent.base_url = "https://api.anthropic.com"
        parent.api_mode = "anthropic_messages"
        ids = ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"]
    else:
        ids = ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-luna"]
    if catalog_kind == "anthropic":
        monkeypatch.setattr(models, "_fetch_anthropic_models", lambda **_: ids)
        assert "claude-fable-5" in models.cached_provider_model_ids(parent.provider, force_refresh=True)
    monkeypatch.setattr(models, "provider_model_ids", lambda *a, **kw: pytest.fail("Unexpected catalog request"))
    if catalog_kind not in {"missing", "anthropic"}:
        fingerprint = (models._credential_fingerprint(parent.provider)
                       if catalog_kind != "other-account" else "other-account")
        models._store_cache_entry(parent.provider, {
            **models._cache_entry(fingerprint, ids), "fallback": catalog_kind == "curated",
        })
    (home / "config.yaml").write_text(yaml.safe_dump({
        "delegation": {
            "backend": "meu_coordinator_general",
            "fallback_providers": [{"provider": "deepseek", "model": "deepseek-v4-pro"}],
        }
    }), encoding="utf-8")

    out = dispatch(parent, [task(), task("standard")])
    out_complex = dispatch(parent, [task("complex")])
    assert [r["status"] for r in out["results"] + out_complex["results"]] == ["completed"] * 3
    expected = ids[:3] if catalog_kind in {"verified", "anthropic"} else [parent.model] * 3
    assert [b["model"] for b in built] == expected
    for child in built:
        assert child["override_provider"] is None
        assert child["routing_cfg"]["fallback_providers"] == []
        keys = ("model", "override_provider", "override_base_url", "override_api_key", "override_api_mode",
                "override_acp_command", "override_acp_args", "routing_cfg")
        runtime = _resolve_child_runtime(parent, {}, parent.api_key, **{key: child.get(key) for key in keys})
        assert (runtime["provider"], runtime["base_url"], runtime["api_mode"], runtime["api_key"]) == (
            parent.provider, parent.base_url, parent.api_mode, parent.api_key,
        )
        assert runtime["fallback_model"] is None


def test_coordinator_does_not_spawn_on_parent_cross_provider_fallback(coordinator):
    _, built, parent = coordinator
    parent._primary_runtime = {"provider": "openai-codex"}
    parent._fallback_activated = True

    out = dispatch(parent, [task()])

    assert "selected provider is temporarily unavailable" in out.get("error", ""), out
    assert built == []


def test_general_resumes_existing_projects_and_honors_only_active_provider_overrides(coordinator, tmp_path):
    from tests.plugins.delegation.test_meu_projects import create, project

    home, built, parent = coordinator
    assert create(parent, tmp_path, [task(id="light"), task("complex", id="heavy")])["ready"] == ["light", "heavy"]
    (home / "config.yaml").write_text(yaml.safe_dump({
        "delegation": {
            "backend": "meu_coordinator_general",
            "backends": {"meu_coordinator_general": {"models": {
                "deepseek": {"routine": "deepseek-flash", "complex": "deepseek-v4-pro"},
                "openai-codex": {"routine": "gpt-6-luna", "complex": "gpt-6.1-sol"},
            }}},
        }
    }), encoding="utf-8")
    parent.provider = "openai-codex"
    parent.model = "gpt-5.6-sol"
    parent.base_url = "https://chatgpt.com/backend-api/codex"
    assert project(parent, "run")["tasks"]["light"]["state"] == "needs_review"
    assert [b["model"] for b in built] == ["gpt-6-luna", "gpt-6.1-sol"]


def test_deepseek_coordinator_refuses_other_providers(coordinator):
    _, built, parent = coordinator
    parent.provider = "openai-codex"
    out = dispatch(parent, [task()])
    assert "requires a DeepSeek session" in out.get("error", ""), out
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
                                  {"write_paths": ["src/*.py"]}, {"workload": "cheap"},
                                  {"tool_access": "terminal"}, {"tool_access": None}])
def test_incomplete_or_invalid_plans_do_not_start_workers(coordinator, patch):
    _, built, parent = coordinator
    out = dispatch(parent, [task(**patch)])
    assert "error" in out and built == []


def test_vision_task_routes_to_flash(coordinator):
    _, built, parent = coordinator
    out = dispatch(parent, [task("vision")])
    assert out["results"][0]["status"] == "completed"
    assert built[0]["model"] == "deepseek-flash"


def test_tool_scope_belongs_to_each_task_even_on_the_same_model_route(coordinator):
    _, built, parent = coordinator
    out = dispatch(parent, [task(tool_access="files_only"), task()])
    assert [row["status"] for row in out["results"]] == ["completed", "completed"]
    assert built[0]["allowed_tools"] == {"read_file", "write_file", "patch", "search_files"}
    assert "allowed_tools" not in built[1]
    assert built[0]["model"] == built[1]["model"] == "deepseek-flash"


def test_schema_is_stable_and_coordinator_is_discoverable_for_settings(coordinator):
    from agent.delegation_backends import list_backends
    from tools.registry import registry
    first = json.dumps(registry.get_definitions({"delegate_task"}), sort_keys=True)
    second = json.dumps(registry.get_definitions({"delegate_task"}), sort_keys=True)
    assert first == second and '"parallel_safe"' in first and '"acceptance"' in first
    backends = {b.name: b for b in list_backends()}
    assert backends["meu_coordinator"].available and backends["meu_coordinator"].label == "Meu Coordinator · DeepSeek"
    assert backends["meu_coordinator_general"].available
    assert backends["meu_coordinator_general"].label == "Meu Coordinator · General"


def test_bundled_first_use_resolves_the_general_backend_by_its_own_name(coordinator, monkeypatch):
    from agent import delegation_registry

    monkeypatch.setattr(delegation_registry, "_first_use", {})
    assert delegation_registry._load_bundled("meu_coordinator_general").name == "meu_coordinator_general"
    assert delegation_registry._load_bundled("meu_coordinator").name == "meu_coordinator"


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
