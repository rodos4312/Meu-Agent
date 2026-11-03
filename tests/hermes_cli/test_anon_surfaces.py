"""Legacy Nous account rendering on the remaining read-only surfaces.

Contract (R-USR-1): wherever a free-tier identity renders (``hermes auth status nous``,
``hermes auth list``, ``hermes status``) the user sees the free-tier label
plus the upgrade hint, and never the internal identity vocabulary. A real account keeps its normal
rendering.
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import (
    anon_auth,
    auth_commands,
    guest_handoff,
    nous_account,
    status_auth,
)
from hermes_cli.auth import _load_auth_store
from hermes_constants import get_hermes_home
from tests.hermes_cli.anon_portal import as_local_desktop_backend, off_local_desktop

WELCOME = "https://welcome-api.nousresearch.com/v1"
# Words that must never appear on a user-facing free-tier surface.
_FORBIDDEN = re.compile(r"guest|anonymous|user id|org id|nas_user|nas_organisation", re.IGNORECASE)


def _jwt(**claims) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    payload = {"sub": "nas_user:abc", "client_id": "nas-anonymous", "account_tier": "anonymous",
               "scope": "inference:invoke", "exp": int(time.time()) + 10 ** 8, **claims}
    return f"{seg({'alg': 'RS256'})}.{seg(payload)}.sig"


def _write_auth(nous_state: dict) -> None:
    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text(json.dumps({"active_provider": "nous", "providers": {"nous": nous_state}}))


def _guest_state() -> dict:
    return {
        "auth_method": "anonymous", "account_tier": "anonymous", "anon_token": "anon_t",
        "access_token": _jwt(), "expires_at": "2030-01-01T00:00:00+00:00",
        "inference_base_url": WELCOME, "user_id": "nas_user:abc", "org_id": "nas_organisation:def",
        anon_auth.WELCOME_CLAIM_FLAG: True,
    }


def _account_state() -> dict:
    return {
        "auth_method": "oauth_device_code", "client_id": "hermes-cli",
        "access_token": _jwt(sub="nas_user:real", client_id="hermes-cli", account_tier="standard", paid_access=True),
        "refresh_token": "rt_live", "expires_at": "2030-01-01T00:00:00+00:00",
        "portal_base_url": "https://portal.nousresearch.com", "inference_base_url": "https://inference-api.nousresearch.com/v1",
    }


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_SHARED_AUTH_DIR", str(tmp_path / "shared-store"))
    # The welcome trial carries inference only on the desktop's local backend.
    as_local_desktop_backend(monkeypatch)
    for var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NOUS_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    # No network: the account lookup is derived from the JWT the store already holds.
    monkeypatch.setattr(nous_account, "_fetch_nous_account_info",
                        lambda *a, **k: pytest.fail("portal fetch must not happen on a read-only surface"))
    nous_account.reset_nous_portal_account_info_cache()
    import hermes_cli.auth as auth_mod
    auth_mod.invalidate_nous_auth_status_cache()
    yield
    nous_account.reset_nous_portal_account_info_cache()
    auth_mod.invalidate_nous_auth_status_cache()


def _render_all(capsys) -> dict[str, str]:
    out: dict[str, str] = {}
    auth_commands.auth_status_command(SimpleNamespace(provider="nous"))
    out["auth status"] = capsys.readouterr().out
    auth_commands.auth_list_command(SimpleNamespace(provider="nous"))
    out["auth list"] = capsys.readouterr().out
    ctx = SimpleNamespace(config={}, nous_logged_in=False, nous_inference_present=False, nous_account_info=None)
    status_auth._render_auth_providers(ctx)
    out["hermes status"] = capsys.readouterr().out
    return out


def test_free_tier_renders_free_tier_copy_on_every_surface(isolated_store, capsys):
    _write_auth(_guest_state())
    rendered = _render_all(capsys)
    for surface, text in rendered.items():
        assert "free tier" in text.lower(), f"{surface} did not name the free tier:\n{text}"
        assert anon_auth.FREE_TIER_LABEL in text and anon_auth.GUEST_MODEL in text, surface
        assert anon_auth.UPGRADE_HINT in text, f"{surface} lacks the upgrade hint:\n{text}"
        leaked = _FORBIDDEN.search(text)
        assert leaked is None, f"{surface} leaked {leaked.group(0)!r}:\n{text}"
    # Billing / entitlement copy for the free tier points at the upgrade path, never at billing.
    info = nous_account.get_nous_portal_account_info()
    assert info.is_anonymous_tier
    message = nous_account.format_nous_portal_entitlement_message(info, capability="managed web tools")
    assert message == nous_account.FREE_TIER_NEEDS_ACCOUNT
    assert "billing" not in message.lower() and _FORBIDDEN.search(message) is None


def test_real_account_keeps_account_rendering(isolated_store, capsys):
    _write_auth(_account_state())
    rendered = _render_all(capsys)
    for surface, text in rendered.items():
        assert "free tier" not in text.lower(), f"{surface} mislabelled a real account:\n{text}"
        assert anon_auth.UPGRADE_HINT not in text, surface
    assert "logged in" in rendered["auth status"]
    assert "credentials" in rendered["auth list"]
    info = nous_account.get_nous_portal_account_info()
    assert not info.is_anonymous_tier
    assert nous_account.format_nous_portal_entitlement_message(info) is None  # paid_access claim entitles


@pytest.mark.parametrize("tier", ["Anonymous", "ANONYMOUS", " anonymous "])
def test_anonymous_tier_matches_case_and_whitespace_insensitively(isolated_store, tier):
    """The tier claim is wire data; casing must not hand a guest billing copy instead of the sign-in copy."""
    _write_auth({**_guest_state(), "account_tier": tier, "access_token": _jwt(account_tier=tier)})
    info = nous_account.get_nous_portal_account_info()
    assert info.is_anonymous_tier
    assert nous_account.format_nous_portal_entitlement_message(info) == nous_account.FREE_TIER_NEEDS_ACCOUNT


def test_guest_whose_lookup_fails_still_gets_the_sign_in_copy(isolated_store, monkeypatch):
    """A token inside its refresh window falls through to the account API; when that fails the
    stored tier must survive on the error snapshot."""
    state = {**_guest_state(), "access_token": _jwt(exp=int(time.time()) + 30),
             "portal_base_url": "http://127.0.0.1:9"}
    _write_auth(state)
    monkeypatch.setattr(nous_account, "_fetch_nous_account_info",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("portal down")))
    info = nous_account.get_nous_portal_account_info()
    assert info.error is not None and info.is_anonymous_tier
    assert nous_account.format_nous_portal_entitlement_message(info) == nous_account.FREE_TIER_NEEDS_ACCOUNT


def test_the_paid_tool_notice_switches_wording_inside_a_chat():
    info = nous_account.NousPortalAccountInfo(
        logged_in=True, source="token", fresh=True, account_tier="anonymous"
    )
    assert nous_account.format_nous_portal_entitlement_message(
        info, in_chat=True
    ) == nous_account.FREE_TIER_NEEDS_ACCOUNT_CHAT
    assert nous_account.format_nous_portal_entitlement_message(
        info, in_chat=False
    ) == nous_account.FREE_TIER_NEEDS_ACCOUNT


def test_a_claimed_guest_reads_as_the_free_tier_on_the_cli_too(isolated_store, monkeypatch, capsys):
    """Once the Desktop claimed the trial, the CLI runs on it as well."""
    off_local_desktop(monkeypatch)
    _write_auth(_guest_state())

    auth_commands.auth_status_command(SimpleNamespace(provider="nous"))
    text = capsys.readouterr().out
    assert "free tier" in text.lower()
