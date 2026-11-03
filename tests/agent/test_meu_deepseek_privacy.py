"""A DeepSeek tool round trip still uses its provider while Nous metrics stay off."""

import json
import urllib.request
from unittest.mock import Mock

import httpx
from openai import OpenAI

from agent.transports.chat_completions import ChatCompletionsTransport
from providers import get_provider_profile


def test_deepseek_tool_call_and_followup_work_without_nous_telemetry(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.url.host == "api.deepseek.com"
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-pro"
        if len(calls) == 1:
            message = {"role": "assistant", "content": None, "reasoning_content": "Need the file tool.", "tool_calls": [{
                "id": "read-1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"note.txt"}'},
            }]}
            finish = "tool_calls"
        else:
            assert body["messages"][-1] == {"role": "tool", "tool_call_id": "read-1", "content": "test content"}
            assert body["messages"][-2]["reasoning_content"]
            message = {"role": "assistant", "content": "Read successfully."}
            finish = "stop"
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        })

    telemetry = Mock(side_effect=AssertionError("Nous telemetry must never be attempted"))
    monkeypatch.setattr(urllib.request, "urlopen", telemetry)
    transport = ChatCompletionsTransport()
    profile = get_provider_profile("deepseek")
    assert profile is not None
    history = [{"role": "user", "content": "Read note.txt"}]
    tools = [{"type": "function", "function": {
        "name": "read_file", "description": "Read an approved file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }}]
    with OpenAI(api_key="test-only", base_url="https://api.deepseek.com/v1", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        first = client.chat.completions.create(**transport.build_kwargs(
            "deepseek-v4-pro", history, tools, provider_profile=profile, base_url=str(client.base_url)))
        normalized = transport.normalize_response(first)
        assert normalized.tool_calls[0].name == "read_file"
        history.extend([first.choices[0].message.model_dump(exclude_none=True), {
            "role": "tool", "tool_call_id": "read-1", "content": "test content",
        }])
        final = client.chat.completions.create(**transport.build_kwargs(
            "deepseek-v4-pro", history, tools, provider_profile=profile, base_url=str(client.base_url)))
        assert transport.normalize_response(final).content == "Read successfully."
    assert len(calls) == 2
    telemetry.assert_not_called()
