"""Real provider/config wiring uses direct browser credentials without a Nous fallback."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from plugins.browser.browser_use.provider import BrowserUseBrowserProvider
from tools import browser_session_cloud as cloud


@pytest.fixture(autouse=True)
def isolated_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("BROWSER_USE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    cloud.reset_caches()

    def unexpected(*args, **kwargs):
        pytest.fail("Browser routing must not consult Nous or send an unexpected request")

    monkeypatch.setattr("tools.managed_tool_gateway.resolve_managed_tool_gateway", unexpected)
    monkeypatch.setattr("hermes_cli.nous_account.get_nous_portal_account_info", unexpected)
    monkeypatch.setattr("requests.sessions.Session.request", unexpected)
    yield
    cloud.reset_caches()


def test_direct_browser_lifecycle_stays_on_vendor(monkeypatch):
    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-direct-key")
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        response = Mock(ok=True, status_code=200, headers={})
        response.json.return_value = {"id": "test-session", "cdpUrl": "wss://browser.example/cdp",
                                      "timeoutAt": "2030-01-01T00:05:00Z"}
        return response

    monkeypatch.setattr("requests.sessions.Session.request",
                        lambda self, method, url, **kw: request(method, url, **kw))
    provider = BrowserUseBrowserProvider()
    assert provider.is_available()
    session = provider.create_session("test-task")
    assert session["expires_at"] == "2030-01-01T00:05:00Z"
    assert provider.close_session(session["bb_session_id"])
    assert [(method, url) for method, url, _ in calls] == [
        ("post", "https://api.browser-use.com/api/v3/browsers"),
        ("patch", "https://api.browser-use.com/api/v3/browsers/test-session"),
    ]
    for _, _, kwargs in calls:
        assert kwargs["headers"] == {"Content-Type": "application/json", "X-Browser-Use-API-Key": "test-direct-key"}


@pytest.mark.parametrize("settings", ["cloud_provider: nous", "use_gateway: true",
                                     "cloud_provider: local\n  use_gateway: true"])
def test_retired_browser_selection_does_not_launch_a_paid_or_local_browser(settings, tmp_path, monkeypatch):
    from tools import browser_use_cli

    (tmp_path / "config.yaml").write_text(f"browser:\n  {settings}\n", encoding="utf-8")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-direct-key")
    monkeypatch.setattr("tools.browser_session_cdp.get_cdp_override", lambda: "")
    monkeypatch.setattr(browser_use_cli, "_resolve_local_cdp", lambda *a, **kw: pytest.fail("Unexpected local fallback"))
    provider = BrowserUseBrowserProvider()
    assert not provider.is_available()
    with pytest.raises(ValueError, match="has been removed"):
        provider.create_session("test-task")
    with pytest.raises(ValueError, match="has been removed"):
        cloud.get_cloud_provider()
    assert "has been removed" in browser_use_cli._resolve_backend_cdp({}, "test-task")


def test_no_key_never_autodetects_a_nous_browser():
    assert not BrowserUseBrowserProvider().is_available()
    assert cloud.get_cloud_provider() is None


def test_picker_exposes_direct_browser_credentials():
    schema = BrowserUseBrowserProvider().get_setup_schema()
    assert [field["key"] for field in schema["env_vars"]] == ["BROWSER_USE_API_KEY"]


@pytest.mark.parametrize("selection", [None, "", "local"])
def test_explicit_local_status_does_not_claim_cloud_key_readiness(selection, monkeypatch):
    from hermes_cli import nous_subscription as status

    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-direct-key")
    monkeypatch.setattr(status, "_has_browser_harness", lambda: True)
    monkeypatch.setattr(status, "_local_browser_runnable", lambda cfg: False)
    state = status._browser_feature({"cloud_provider": selection}, True)
    assert not state.available
    assert not state.active
    assert state.explicit_configured
    assert not state.managed_by_nous
