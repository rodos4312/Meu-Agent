"""Tests for the resolve_nous_access_token startup-burst memo (PR #66016).

The memo collapses the startup burst of managed-tool check_fn calls into a
single expensive resolution: within the short TTL, repeat calls return the
cached token without re-entering _provider_state_transaction (two
cross-process file locks + state reads) or triggering a network refresh.
"""

import json
import time

import pytest

from hermes_cli import auth


@pytest.fixture(autouse=True)
def _fresh_memo(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_PORTAL_BASE_URL", raising=False)
    monkeypatch.delenv("PROVIDER_A_PORTAL_URL", raising=False)
    monkeypatch.setattr(auth, "_RESOLVE_TOKEN_CACHE", {})
    yield


def _write_valid_auth_file(tmp_path, token="memo-token"):
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider": "provider-a",
                "providers": {
                    "provider-a": {
                        "access_token": token,
                        "refresh_token": "r",
                        "client_id": "hermes-cli-vps",
                        "expires_at": time.strftime(
                            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3600)
                        ),
                    }
                },
            }
        )
    )


def _count_transactions(monkeypatch):
    calls = {"n": 0}
    real = auth._provider_state_transaction

    def _counting(provider):
        calls["n"] += 1
        return real(provider)

    monkeypatch.setattr(auth, "_provider_state_transaction", _counting)
    return calls

