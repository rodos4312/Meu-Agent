"""An explicit OpenRouter pair owns ordinary as well as complex helper work."""
import json

import hermes_yaml as yaml
import pytest


@pytest.mark.parametrize("workload", ["routine", "standard", "complex", "vision"])
def test_selected_openrouter_pair_excludes_other_catalog_models(coordinator, monkeypatch, workload):
    from hermes_cli import models
    from tools.delegate_tool_config import _resolve_child_runtime
    from tools.registry import registry

    home, built, parent = coordinator
    parent.provider = "openrouter"
    # The chat can be manually changed without changing the chosen helper pair.
    parent.model = "other/sonnet"
    parent.base_url = "https://openrouter.ai/api/v1"
    parent.api_key = "synthetic-openrouter-key"
    parent.api_mode = "chat_completions"
    monkeypatch.setenv("OPENROUTER_API_KEY", parent.api_key)
    models._store_cache_entry("openrouter", models._cache_entry(
        models._credential_fingerprint("openrouter"),
        ["vendor/selected-lite", "vendor/selected-pro", "other/sonnet"],
    ))
    (home / "config.yaml").write_text(yaml.safe_dump({"delegation": {
        "backend": "meu_coordinator_general",
        "backends": {"meu_coordinator_general": {"models": {
            "openrouter": {"routine": "vendor/selected-lite", "complex": "vendor/selected-pro"},
            "deepseek": {"routine": "wrong-provider-model"},
        }}},
    }}), encoding="utf-8")
    result = json.loads(registry.dispatch("delegate_task", {"background": False, "tasks": [{
        "goal": "Check this bounded project result", "acceptance": "Report the observed check",
        "workload": workload, "parallel_safe": True, "write_paths": [],
    }]}, parent_agent=parent))
    assert result["results"][0]["status"] == "completed", result
    expected = "vendor/selected-lite" if workload == "routine" else "vendor/selected-pro"
    assert built[0]["model"] == expected
    fields = ("model", "override_provider", "override_base_url", "override_api_key", "override_api_mode",
              "override_acp_command", "override_acp_args", "routing_cfg")
    runtime = _resolve_child_runtime(parent, {}, parent.api_key, **{key: built[0].get(key) for key in fields})
    assert (runtime["provider"], runtime["base_url"], runtime["api_key"]) == (
        parent.provider, parent.base_url, parent.api_key,
    )
    assert runtime["fallback_model"] is None


@pytest.mark.parametrize("supports_vision", [True, False])
def test_explicit_pair_keeps_vision_within_selected_models(monkeypatch, supports_vision):
    from types import SimpleNamespace

    from agent.delegation_provider import DelegationRouteError
    from plugins.delegation.meu_coordinator.routing import select_model

    monkeypatch.setattr("agent.models_dev.get_model_capabilities", lambda provider, model:
                        SimpleNamespace(supports_vision=model == "vendor/strong" and supports_vision))
    route = {"provider": "openrouter", "model": "other/vision-model"}
    choices = {"openrouter": {"routine": "vendor/light", "complex": "vendor/strong"}}
    if supports_vision:
        assert select_model("vision", route, choices) == "vendor/strong"
    else:
        with pytest.raises(DelegationRouteError, match="selected.*vision"):
            select_model("vision", route, choices)
