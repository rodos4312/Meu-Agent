"""Diagnostic suppression preserves real producer outcomes and control paths."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent import empty_response_guard
from agent.status_output import StatusOutputMixin

from agent.turn_empty_response import _terminal_empty
from gateway.config import Platform
from gateway.run import GatewayRunner, _load_gateway_config
from gateway.run_turn_runner import TurnRunner
from gateway.session import SessionSource
from gateway.turn_context import TurnContext


class Agent(StatusOutputMixin):
    suppress_status_output = True
    log_prefix = ""
    provider = "provider-a"
    model = "model"
    base_url = "https://example.invalid/v1"
    _fallback_chain = []
    _empty_content_retries = 3

    def _try_activate_fallback(self):
        return False

    def _persist_session(self, *args):
        self.persisted = True

    def _extract_reasoning(self, *args):
        return ""

    def _drop_trailing_empty_response_scaffolding(self, *args):
        pass

    def _build_assistant_message(self, *args):
        return {"role": "assistant"}


@pytest.mark.parametrize("yaml_text,expected", [
    ("display: broken", True), ("display: [broken]", True),
    ("display: {platforms: broken}", True),
    ("display: {suppress_warning_notifications: true, platforms: broken}", False),
])
def test_bad_config_containers_do_not_abort_startup_warning(tmp_path, monkeypatch, yaml_text, expected):
    from gateway import run

    (tmp_path / "config.yaml").write_text(yaml_text)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(run, "_hermes_home", tmp_path)
    gateway = object.__new__(GatewayRunner)
    gateway._session_db_init_error = "database is locked"
    gateway._session_db_handle_cache = None
    gateway._home_channel_transports = lambda: [(Platform.SLACK, None, None, None)]
    gateway._send_home_channel_message = AsyncMock()
    asyncio.run(gateway._send_session_db_warning_notifications())
    assert gateway._send_home_channel_message.await_count == int(expected)
