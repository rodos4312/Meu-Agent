"""Multiplex invariant: a scoped API key is never paired with the DEFAULT profile's base URL / proxy.

`agent/auxiliary_client.py` already scopes provider keys via ``_scoped_key_env``; the base URLs beside
them (OPENAI_BASE_URL, XAI_BASE_URL, PROVIDER_A_BASE_URL) and the gateway proxy URL / browser
provider endpoints must follow the same rule, or a secondary's key is sent to another profile's host.
"""
from __future__ import annotations

import pytest

from agent import secret_scope


@pytest.fixture
def secondary_scope(monkeypatch):
    for name in ("OPENAI_BASE_URL", "XAI_BASE_URL", "HERMES_XAI_BASE_URL", "PROVIDER_A_BASE_URL",
                 "GATEWAY_PROXY_URL", "FIRECRAWL_API_URL", "BROWSERBASE_BASE_URL", "XAI_API_KEY"):
        monkeypatch.setenv(name, f"https://{name.lower()}.default.example/v1")
    secret_scope.set_multiplex_active(True)
    token = secret_scope.set_secret_scope({"BROWSERBASE_API_KEY": "bb-b", "BROWSERBASE_PROJECT_ID": "pid-b"})
    try:
        yield
    finally:
        secret_scope.reset_secret_scope(token)
        secret_scope.set_multiplex_active(False)

