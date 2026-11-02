"""Auto routing stays local, respects modalities, and preserves complete tool conversations."""

import copy
import json

import httpx
import pytest
from openai import OpenAI


@pytest.fixture
def profile():
    import model_tools  # discover real provider plugins
    from providers import get_provider_profile

    return get_provider_profile("deepseek")


@pytest.mark.parametrize("text, expected", [
    ("Καλημέρα, τι κάνεις;", "deepseek-flash"),
    ("Άνοιξε το σημειωματάριο", "deepseek-flash"),
    ("Διόρθωσε τον κώδικα και κάνε ανάλυση του σφάλματος", "deepseek-v4-pro"),
    ("Implement an algorithm and prove it terminates", "deepseek-v4-pro"),
    ("Analyze and compare these approaches", "deepseek-v4-pro"),
    ("diorthose ton kodika", "deepseek-v4-pro"),
    ("A long request. " * 80, "deepseek-v4-pro"),
])
def test_local_request_classification(profile, text, expected):
    messages = [{"role": "user", "content": text}]
    assert profile.resolve_request_model("deepseek-v4-pro", messages=messages, policy={"enabled": True}) == expected
    assert profile.resolve_request_model("deepseek-v4-pro", messages=messages, policy={"enabled": False}) == "deepseek-v4-pro"
    assert profile.resolve_request_model("custom-model", messages=messages, policy={"enabled": True}) == "custom-model"


def test_tool_results_and_continuations_keep_the_selected_route(profile):
    messages = [{"role": "system", "content": "Frozen system prompt"},
                {"role": "user", "content": "Debug this code"}]
    before = copy.deepcopy(messages)
    assert profile.resolve_request_model("deepseek-flash", messages=messages, policy={"enabled": True}) == "deepseek-v4-pro"
    assert messages == before
    messages.extend([{"role": "assistant", "content": None, "tool_calls": []},
                     {"role": "tool", "tool_call_id": "one", "content": "Short output"}])
    assert profile.resolve_request_model("deepseek-flash", messages=messages, policy={"enabled": True}) == "deepseek-v4-pro"
    messages.append({"role": "user", "content": "συνέχισε"})
    assert profile.resolve_request_model("deepseek-flash", messages=messages, policy={"enabled": True}) == "deepseek-v4-pro"
    messages.append({"role": "user", "content": "Ευχαριστώ!"})
    assert profile.resolve_request_model("deepseek-flash", messages=messages, policy={"enabled": True}) == "deepseek-flash"


def test_images_in_history_and_tool_results_require_flash(profile):
    for role in ("user", "tool"):
        messages = [{"role": role, "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA="}}]},
                    {"role": "user", "content": "Analyze this complicated architecture"}]
        assert profile.resolve_request_model("deepseek-v4-pro", messages=messages, policy={"enabled": True}) == "deepseek-flash"


def test_real_agent_config_persistence_and_sdk_tool_round_trip(tmp_path, monkeypatch):
    from hermes_cli.config_backend import write_config_document
    from run_agent import AIAgent
    from agent.request_routing import active_request_model

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    write_config_document(config_path, {"smart_model_routing": {"enabled": True}})

    def agent():
        return AIAgent(model="deepseek-flash", provider="deepseek", api_key="test-only",
                       base_url="https://api.deepseek.com/v1", enabled_toolsets=[],
                       quiet_mode=True, skip_memory=True, skip_context_files=True)

    current = agent()
    history = [{"role": "system", "content": "Frozen prefix"}, {"role": "user", "content": "Debug this code"}]
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {}}}}]
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.host == "api.deepseek.com"
        assert body["model"] == "deepseek-v4-pro"
        assert body["messages"][0]["content"] == "Frozen prefix"
        message = {"role": "assistant", "content": "Done", "reasoning_content": "checked"}
        if len(calls) == 1:
            message.update(content=None, tool_calls=[{"id": "one", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}])
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0, "model": body["model"],
                                      "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if len(calls) == 1 else "stop"}]})

    with OpenAI(api_key="test-only", base_url="https://api.deepseek.com/v1", http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
        first = client.chat.completions.create(**current._build_api_kwargs(history, tools))
        history.extend([first.choices[0].message.model_dump(exclude_none=True), {"role": "tool", "tool_call_id": "one", "content": "result"}])
        assert client.chat.completions.create(**current._build_api_kwargs(history, tools)).choices[0].message.content == "Done"
    assert len(calls) == 2
    assert current.model == "deepseek-flash"
    assert active_request_model(current) == "deepseek-v4-pro"
    from types import SimpleNamespace
    from agent.turn_usage import record_response_usage

    priced_models = []
    from agent import turn_usage
    real_estimate = turn_usage.estimate_usage_cost

    def estimate(*args, **kwargs):
        priced_models.append(args[0] if args else kwargs["model"])
        return real_estimate(*args, **kwargs)

    monkeypatch.setattr(turn_usage, "estimate_usage_cost", estimate)
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=7, total_tokens=107))
    record_response_usage(current, response, messages=history, api_call_count=1, api_duration=0.1,
                          compression_attempts=0, max_compression_attempts=3)
    assert priced_models == ["deepseek-v4-pro"]
    assert calls[1]["messages"][2]["reasoning_content"] == "checked"
    assert agent()._model_routing_config["enabled"] is True
    write_config_document(config_path, {"smart_model_routing": {"enabled": False}})
    manual = agent()
    assert manual._build_api_kwargs(history, tools)["model"] == "deepseek-flash"
    # Existing conversations retain their frozen choice of routing policy.
    assert current._build_api_kwargs(history, tools)["model"] == "deepseek-v4-pro"


def test_active_turn_is_pinned_but_new_images_still_use_vision(profile):
    from types import SimpleNamespace
    from agent.request_routing import prepare_routed_request

    agent = SimpleNamespace(model="deepseek-flash", provider="deepseek", _model_routing_config={"enabled": True},
                            _current_turn_id="one", _inflight_turn_id="one",
                            _prepare_messages_for_non_vision_model=lambda messages, **kw: messages)
    messages = [{"role": "user", "content": "Debug this code"}]
    assert prepare_routed_request(agent, profile, messages)[0] == "deepseek-v4-pro"
    messages.append({"role": "user", "content": "Finish now"})
    assert prepare_routed_request(agent, profile, messages)[0] == "deepseek-v4-pro"
    agent._current_turn_id = agent._inflight_turn_id = "two"
    assert prepare_routed_request(agent, profile, messages)[0] == "deepseek-flash"


def test_actual_pro_agent_preserves_images_when_auto_routes_to_flash(tmp_path, monkeypatch):
    from hermes_cli.config_backend import write_config_document
    from run_agent import AIAgent

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_config_document(tmp_path / "config.yaml", {"smart_model_routing": {"enabled": True}})
    agent = AIAgent(model="deepseek-v4-pro", provider="deepseek", api_key="test-only",
                    base_url="https://api.deepseek.com/v1", enabled_toolsets=[], quiet_mode=True,
                    skip_memory=True, skip_context_files=True)
    messages = [{"role": "user", "content": [{"type": "text", "text": "Analyze this screenshot"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA="}}]}]
    before = copy.deepcopy(messages)
    kwargs = agent._build_api_kwargs(messages, [])
    assert kwargs["model"] == "deepseek-flash"
    assert kwargs["messages"][0]["content"][1]["type"] == "image_url"
    assert messages == before
    assert agent.model == "deepseek-v4-pro"
