"""Direct web requests survive removal of the Nous-hosted search route."""

import asyncio
import json

import httpx
import pytest

from tests.tools.conftest import register_all_web_providers


@pytest.fixture
def web_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TOOL_GATEWAY_DOMAIN", "nousresearch.com")
    monkeypatch.setenv("TOOL_GATEWAY_USER_TOKEN", "retired-account-token")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    register_all_web_providers()
    from tools.web_result_cache import search_memo

    search_memo.clear()
    yield tmp_path
    from agent.web_search_registry import _reset_for_tests

    _reset_for_tests()


def test_keyless_search_uses_vendor_directly(web_home, monkeypatch):
    from plugins.web.tavily import provider
    from tools.web_tools import web_search_tool

    (web_home / "config.yaml").write_text("web:\n  backend: tavily\n", encoding="utf-8")
    requests = []

    def post(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200, json={"results": [
            {"title": "Example", "url": "https://example.com", "content": "Found page"},
        ]})

    monkeypatch.setattr(provider.httpx, "post", post)
    result = json.loads(web_search_tool("direct search regression"))
    assert result["success"] is True
    assert result["data"]["web"][0]["description"] == "Found page"
    assert len(requests) == 1
    url, kwargs = requests[0]
    assert url == "https://api.tavily.com/search"
    assert "Authorization" not in kwargs["headers"]
    assert "retired-account-token" not in json.dumps(kwargs)


@pytest.mark.parametrize("capability", ["search", "extract"])
def test_retired_provider_requires_selection_without_network(web_home, monkeypatch, capability):
    from tools import web_tools

    (web_home / "config.yaml").write_text("web:\n  backend: nous\n", encoding="utf-8")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "another-billing-account")

    def no_request(*args, **kwargs):
        pytest.fail("A retired selection must not send a request or charge another account")

    monkeypatch.setattr(httpx, "post", no_request)

    async def public_url(_url):
        return True

    monkeypatch.setattr(web_tools, "async_is_safe_url", public_url)
    result = json.loads(web_tools.web_search_tool("retired route") if capability == "search"
                        else asyncio.run(web_tools.web_extract_tool(["https://example.com"])))
    assert result["success"] is False
    assert "nous" in result["error"]
