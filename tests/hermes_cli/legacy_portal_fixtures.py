"""Offline portal fixtures for the remaining legacy tool-gateway compatibility tests."""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest

from hermes_cli import anon_auth

WELCOME = "https://welcome-api.nousresearch.com/v1"
INFERENCE = "https://inference-api.nousresearch.com/v1"
PORTAL = "https://portal.example.test"
REFRESH_TOKEN = "rt-upgraded-1"
EMAIL = "sid@example.test"


def _jwt(**claims) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    payload = {"sub": "nas_user:1", "client_id": "nas-anonymous", "account_tier": "anonymous",
               "scope": "inference:invoke", "exp": int(time.time()) + 900, **claims}
    return f"{seg({'alg': 'RS256'})}.{seg(payload)}.sig"


class FakePortal:
    """NAS anonymous surface + device-code endpoints. Records every call; scenarios flip behaviour."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.minted = 0
        self.claims: list[tuple[str, dict]] = []    # (authorization header, body) per claim call
        self.device_code = "dev-code-123"
        self.user_code = "ABCD-EFGH"
        self.expires_in = 600
        self.token_pending = False        # answer authorization_pending until flipped
        self.token_error = ""             # an RFC 8628 error code the token endpoint answers with
        self.on_token = None              # called when the token grant is issued
        self.token_grants = 0
        self.token_polls = 0
        self.claim_reply = {"status": "claimed", "account_email": EMAIL, "cohort_carried": False,
                            "connectors": {"kind": "moved", "moved_toolkits": ["gmail"], "dropped_toolkits": []}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path.startswith("/api/anonymous/") and not request.headers.get("x-anonymous-api-secret"):
            return httpx.Response(401, json={"error": "invalid_shared_secret"})
        if path == "/api/anonymous/create":
            self.minted += 1
            return httpx.Response(201, json={"user_id": f"nas_user:{self.minted}", "org_id": "nas_org:1",
                                             "token": f"anon_{self.minted:04d}", "idle_ttl_days": 14})
        if path == "/api/anonymous/token":
            return httpx.Response(200, json={"access_token": _jwt(), "token_type": "Bearer", "expires_in": 900,
                                             "user_id": "nas_user:1", "org_id": "nas_org:1",
                                             "inference_base_url": WELCOME})
        if path == "/api/anonymous/claim":
            self.claims.append((request.headers.get("authorization", ""), json.loads(request.content)))
            return httpx.Response(200, json=self.claim_reply)
        if path == "/api/oauth/device/code":
            return httpx.Response(200, json={
                "device_code": self.device_code, "user_code": self.user_code,
                "verification_uri": f"{PORTAL}/device",
                "verification_uri_complete": f"{PORTAL}/device?user_code={self.user_code}",
                "expires_in": self.expires_in, "interval": 1})
        if path == "/api/oauth/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get("grant_type") != "urn:ietf:params:oauth:grant-type:device_code":
                return httpx.Response(400, json={"error": "unsupported_grant_type"})
            if form.get("device_code") != self.device_code:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.token_polls += 1
            if self.token_error:
                return httpx.Response(400, json={"error": self.token_error})
            if self.token_pending:
                return httpx.Response(400, json={"error": "authorization_pending"})
            self.token_grants += 1
            if self.on_token is not None:
                self.on_token()
            return httpx.Response(200, json={
                "access_token": _jwt(sub="nas_user:9", client_id="hermes-cli", account_tier="free", email=EMAIL),
                "refresh_token": REFRESH_TOKEN, "token_type": "Bearer", "expires_in": 900,
                "scope": "inference:invoke", "inference_base_url": INFERENCE})
        return httpx.Response(500, json={"error": f"unexpected {path}"})


@pytest.fixture
def portal(monkeypatch, tmp_path):
    fake = FakePortal()
    monkeypatch.setenv("HERMES_PORTAL_BASE_URL", PORTAL)
    monkeypatch.setenv("HERMES_ANON_API_SECRET", "test-secret")
    monkeypatch.setenv("HERMES_SHARED_AUTH_DIR", str(tmp_path / "shared-store"))
    for var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NOUS_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    from hermes_cli import auth_nous

    def _client(timeout_seconds, verify):
        return httpx.Client(transport=httpx.MockTransport(fake.handler), base_url=PORTAL)
    monkeypatch.setattr(auth_nous, "_nous_http_client", _client)
    real_client = httpx.Client

    class _RoutedClient(real_client):
        def __init__(self, *a, **kw):
            kw.pop("verify", None)
            kw["transport"] = httpx.MockTransport(fake.handler)
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "Client", _RoutedClient)
    anon_auth.reset_mint_memo_for_tests()
    return fake


FREE_PICK = "upstage/solar-pro4:free"


@pytest.fixture
def free_account(monkeypatch):
    """The signed-in account is a $0 (free-plan) account: the Portal's tier read and its recommended
    free list are the only network egress the default pick has, stubbed at their seams."""
    from hermes_cli import models as m
    from hermes_cli import models_pricing as mp
    monkeypatch.setattr(m, "check_nous_free_tier", lambda **kw: True)
    monkeypatch.setattr(m, "fetch_nous_recommended_models", lambda *a, **kw: {
        "freeRecommendedModels": [{"modelName": FREE_PICK}]})
    monkeypatch.setattr(mp, "get_pricing_for_provider", lambda *a, **kw: {})
    monkeypatch.setattr(mp, "nous_policy_allowed_ids", lambda **kw: None)


def _write_model_config(model_cfg: dict) -> None:
    from hermes_cli.config import load_config, save_config
    config = load_config()
    config["model"] = model_cfg
    save_config(config)


def _model_config() -> dict:
    from hermes_cli.config import load_config_readonly
    return dict(load_config_readonly().get("model") or {})
