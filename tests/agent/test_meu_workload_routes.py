"""Explicit multi-provider roles preserve image bytes, credentials and session identity."""
import copy
import json

import httpx
import pytest
from openai import OpenAI


def policy():
    return {
        "enabled": True, "provider": "deepseek", "base_model": "deepseek-v4-pro",
        "routes": {
            "routine": {"provider": "zai", "model": "glm-5.3-flash"},
            "complex": {"provider": "deepseek", "model": "deepseek-v4-pro"},
            "web": {"provider": "gemini", "model": "gemini-3.6-flash"},
            "vision": {"provider": "zai", "model": "glm-5.3-flash"},
        },
    }


@pytest.mark.parametrize("text,provider,model", [
    ("Καλημέρα", "zai", "glm-5.3-flash"),
    ("Debug this complex architecture", "deepseek", "deepseek-v4-pro"),
    ("Implement a search function in this code", "deepseek", "deepseek-v4-pro"),
    ("Search the web for current news", "gemini", "gemini-3.6-flash"),
])
def test_each_explicit_role_selects_its_own_provider(text, provider, model):
    from agent.workload_routes import choose_workload_route
    messages = [{"role": "user", "content": text}]
    before = copy.deepcopy(messages)
    assert choose_workload_route(policy(), "deepseek", messages) == {"provider": provider, "model": model}
    assert choose_workload_route(policy(), "anthropic", messages) is None
    assert messages == before


def test_explicit_image_role_is_used_before_text_only_primary_preprocessing():
    from agent.image_routing import decide_image_input_mode
    from agent.workload_routes import choose_workload_route
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Debug this screenshot"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,cGl4ZWxz"}},
    ]}]
    assert choose_workload_route(policy(), "deepseek", messages) == policy()["routes"]["vision"]
    assert decide_image_input_mode("deepseek", "deepseek-v4-pro", {"smart_model_routing": policy()}) == "native"
    bad = policy()
    bad["routes"]["vision"] = {"provider": "deepseek", "model": "deepseek-v4-pro"}
    with pytest.raises(ValueError, match="does not support images"):
        choose_workload_route(bad, "deepseek", messages)


@pytest.mark.parametrize("provider", ["made-up-provider", "auto", ""])
def test_unknown_provider_is_refused(provider):
    from agent.workload_routes import explicit_routes
    value = policy()
    value["routes"]["routine"]["provider"] = provider
    with pytest.raises(ValueError):
        explicit_routes(value)


def test_real_sdk_sends_image_and_only_the_selected_route_key_then_restores(tmp_path, monkeypatch):
    from agent import auxiliary_client, client_lifecycle
    from agent.voice_turn_route import session_runtime_view
    from agent.workload_turn_route import begin_workload_turn_route, end_workload_turn_route
    from hermes_cli.config_backend import write_config_document
    from run_agent import AIAgent
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_config_document(tmp_path / "config.yaml", {"smart_model_routing": policy()})
    current = AIAgent(
        model="deepseek-v4-pro", provider="deepseek", api_key="deepseek-fixture",
        base_url="https://api.deepseek.com/v1", enabled_toolsets=[],
        quiet_mode=True, skip_memory=True, skip_context_files=True,
    )
    seen = []
    def handle(request):
        data = json.loads(request.content)
        seen.append((request.url.host, request.headers["authorization"], data))
        return httpx.Response(200, json={
            "id": "fixture", "object": "chat.completion", "created": 0,
            "model": data["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Image received"}}],
        })
    chosen = OpenAI(api_key="zai-fixture", base_url="https://api.z.ai/api/paas/v4",
                    http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    def resolve(provider, **kwargs):
        assert provider == "zai" and kwargs["model"] == "glm-5.3-flash"
        return chosen, kwargs["model"]
    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", resolve)
    monkeypatch.setattr(client_lifecycle, "get_provider_request_timeout", lambda *args: None)
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,cGl4ZWxz"}}
    messages = [{"role": "system", "content": "Stable prefix"},
                {"role": "user", "content": [{"type": "text", "text": "Read this screenshot"}, image]}]
    original = copy.deepcopy(messages)
    try:
        assert begin_workload_turn_route(current, messages, "Stable prefix") == "Stable prefix"
        assert current.provider == "zai"
        from agent.auxiliary_task_config import _get_auxiliary_task_config
        assert _get_auxiliary_task_config("vision")["provider"] == "zai"
        assert _get_auxiliary_task_config("vision")["fallback_chain"] == []
        assert session_runtime_view(current).provider == "deepseek"
        current.client.chat.completions.create(**current._build_api_kwargs(messages, []))
        assert seen[0][0] == "api.z.ai"
        assert seen[0][1] == "Bearer zai-fixture"
        assert seen[0][2]["model"] == "glm-5.3-flash"
        assert seen[0][2]["messages"][-1]["content"][-1] == image
        assert messages == original
    finally:
        end_workload_turn_route(current)
        assert current.provider == "deepseek"
        assert current.model == "deepseek-v4-pro"
        assert current.api_key == "deepseek-fixture"
        current.close()
        chosen.close()


def test_virtual_auto_anchor_keeps_actual_primary_provider_and_model():
    from gateway.session_model_mode import GENERAL_AUTO_MODEL, apply_selection, decorate_options
    cfg = {"model": {"provider": "deepseek", "default": "deepseek-v4-pro"},
           "smart_model_routing": policy()}
    assert apply_selection(GENERAL_AUTO_MODEL, "deepseek", cfg) == "deepseek-v4-pro"
    result = decorate_options({
        "provider": "deepseek", "model": "deepseek-v4-pro",
        "providers": [{"slug": "deepseek", "models": ["deepseek-flash", "deepseek-v4-pro"]}],
    }, cfg)
    assert result["model"] == GENERAL_AUTO_MODEL
    assert result["providers"][0]["models"][0] == GENERAL_AUTO_MODEL


@pytest.mark.parametrize("interrupt", [False, True])
def test_full_turn_restores_route_after_completion_or_failure(tmp_path, monkeypatch, interrupt):
    from agent import auxiliary_client
    from run_agent import AIAgent
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_hermes_home
    from hermes_cli.config_backend import write_config_document
    with FakeLLMServer([]) as primary, FakeLLMServer([Text("light reply")]) as light:
        home = write_hermes_home(tmp_path / "home", primary.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        settings = policy()
        write_config_document(home / "config.yaml", {"smart_model_routing": settings})
        agent = AIAgent(model="deepseek-v4-pro", provider="deepseek", base_url=primary.base_url,
                        api_key="deepseek-fixture", enabled_toolsets=["memory"], quiet_mode=True,
                        skip_context_files=True, skip_memory=True)
        chosen = OpenAI(api_key="zai-fixture", base_url=light.base_url)
        def resolve(provider, **kwargs):
            assert provider == "zai"
            if interrupt:
                raise ValueError("fixture unavailable")
            return chosen, kwargs["model"]
        monkeypatch.setattr(auxiliary_client, "resolve_provider_client", resolve)
        try:
            if interrupt:
                with pytest.raises(ValueError, match="fixture unavailable"):
                    agent.run_conversation("Καλημέρα")
            else:
                result = agent.run_conversation("Καλημέρα")
                assert result["final_response"] == "light reply"
                assert [r["model"] for r in light.main_requests()] == ["glm-5.3-flash"]
                assert primary.main_requests() == []
            assert agent.provider == "deepseek"
            assert agent.model == "deepseek-v4-pro"
            assert agent.api_key == "deepseek-fixture"
            assert agent._workload_route_state is None
        finally:
            agent.close()
            chosen.close()


@pytest.mark.parametrize("provider,env_name,endpoint", [
    ("zai", "ZAI_API_KEY", "api.z.ai"),
    ("deepseek", "DEEPSEEK_API_KEY", "api.deepseek.com"),
    ("gemini", "GEMINI_API_KEY", "generativelanguage.googleapis.com"),
])
def test_official_resolver_uses_each_providers_own_saved_key(tmp_path, monkeypatch, provider, env_name, endpoint):
    from hermes_cli.runtime_provider import resolve_runtime_provider
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for name in ("ZAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, name + "-fixture")
    model = {"zai": "glm-5.3-flash", "deepseek": "deepseek-v4-pro", "gemini": "gemini-3.6-flash"}[provider]
    route = resolve_runtime_provider(requested=provider, target_model=model)
    assert route["api_key"] == env_name + "-fixture"
    assert endpoint in route["base_url"]
