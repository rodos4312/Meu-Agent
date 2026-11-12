"""Boot probes run inside the launch profile's scope under multiplex.

``get_tool_definitions`` runs every ``check_fn``; the vision probe resolves Nous runtime
credentials, whose Portal / inference routing overrides read through ``agent.secret_scope.get_secret``.
With multiplex active and no scope on the executor thread that read fails closed, the override is
absent, and a non-production Portal's refresh token is POSTed to the production Portal. The warm-up
must run under the same binding a routed turn gets, and the binding must reach the executor thread.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from agent import secret_scope
from gateway import run as gateway_run
from gateway.run_startup import GatewayStartupMixin

PORTAL = "https://portal.staging-nousresearch.com"


@pytest.fixture
def multiplex_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(f"HERMES_PORTAL_BASE_URL={PORTAL}\n")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_PORTAL_BASE_URL", raising=False)
    monkeypatch.delenv("PROVIDER_A_PORTAL_URL", raising=False)
    secret_scope.set_multiplex_active(True)
    try:
        yield home
    finally:
        secret_scope.set_multiplex_active(False)


def _probe(seen: dict):
    def probe() -> int:
        from hermes_cli.auth_nous import _nous_portal_env_override
        seen["scope_installed"] = secret_scope._SECRET_SCOPE.get() is not None
        seen["portal_override"] = _nous_portal_env_override()
        return 1
    return probe


class _Runner(GatewayStartupMixin):
    def __init__(self, *, multiplex: bool):
        self.config = types.SimpleNamespace(multiplex_profiles=multiplex)


def _run_warmup(monkeypatch, *, multiplex: bool) -> dict:
    """Drive ``_warm_turn_prerequisites`` with the sync warm-up replaced by a probe that records what
    the executor thread can see, then what the loop task sees once the warm-up has returned."""
    seen: dict = {}
    monkeypatch.setattr(gateway_run, "_warm_turn_machinery_sync", _probe(seen))

    async def drive() -> None:
        await _Runner(multiplex=multiplex)._warm_turn_prerequisites()
        # Same task as the warm-up (asyncio.run copies the context, so the caller's view proves nothing).
        from hermes_constants import get_hermes_home_override
        seen["scope_after"] = secret_scope._SECRET_SCOPE.get()
        seen["home_override_after"] = get_hermes_home_override()

    asyncio.run(drive())
    return seen

