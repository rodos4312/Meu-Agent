"""Behavior contracts for the data-only community MT5 adapter; no live MT5."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "optional-skills/research/mt5-market-data/scripts/readonly_server.py"


@pytest.fixture
def reader():
    spec = importlib.util.spec_from_file_location("meu_mt5_reader_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def terminal(tmp_path):
    path = tmp_path / "selected" / "terminal64.exe"
    path.parent.mkdir()
    path.write_bytes(b"fixture - never executed")
    return path


class Registry:
    def __init__(self, names):
        self.tools = {name: Mock(name=name) for name in names}

    async def list_tools(self):
        return [SimpleNamespace(name=name) for name in self.tools]

    def remove_tool(self, name):
        del self.tools[name]

    def call(self, name):
        return self.tools[name]()


def test_protocol_registry_rejects_trade_and_unknown_tools(reader):
    blocked = {"place_order", "modify_order", "cancel_order", "close_position",
               "get_chart_screenshot", "future_execution_tool"}
    server = Registry(reader.READ_TOOLS | blocked)
    original = dict(server.tools)
    assert asyncio.run(reader.keep_read_tools(server)) == sorted(reader.READ_TOOLS)
    for name in blocked:
        with pytest.raises(KeyError):
            server.call(name)
        original[name].assert_not_called()
    server.call("get_quote")
    original["get_quote"].assert_called_once()


def test_incomplete_upstream_contract_refuses_startup(reader):
    server = Registry(reader.READ_TOOLS - {"get_rates"})
    with pytest.raises(RuntimeError, match="contract"):
        asyncio.run(reader.keep_read_tools(server))


@pytest.mark.parametrize("operation", [
    "order_send", "order_check", "login", "symbol_select", "market_book_add", "UNKNOWN_FUNCTION",
])
def test_sdk_never_dispatches_blocked_operation(reader, terminal, operation):
    function = Mock()
    sdk = SimpleNamespace(**{operation: function})
    proxy = reader.ReadOnlySDK(sdk, terminal)
    with pytest.raises(PermissionError):
        getattr(proxy, operation)
    function.assert_not_called()


def test_sdk_read_and_scalar_constants_work(reader, terminal):
    sdk = SimpleNamespace(symbol_info_tick=Mock(return_value="quote"), TIMEFRAME_H1=16385)
    proxy = reader.ReadOnlySDK(sdk, terminal)
    assert proxy.symbol_info_tick("XAUUSD.a") == "quote"
    sdk.symbol_info_tick.assert_called_once_with("XAUUSD.a")
    assert proxy.TIMEFRAME_H1 == 16385


def test_connection_attaches_only_to_selected_existing_session(reader, terminal):
    sdk = SimpleNamespace(
        initialize=Mock(return_value=True), shutdown=Mock(),
        terminal_info=Mock(return_value=SimpleNamespace(path=str(terminal.parent), connected=True)),
    )
    proxy = reader.ReadOnlySDK(sdk, terminal)
    assert proxy.initialize(str(terminal))
    sdk.initialize.assert_called_once_with(str(terminal), timeout=10000)
    with pytest.raises(PermissionError):
        proxy.initialize(str(terminal), login=123, password="not-a-real-password")
    with pytest.raises(PermissionError):
        proxy.initialize()
    assert sdk.initialize.call_count == 1


def test_wrong_terminal_disconnects_before_serving(reader, terminal, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    sdk = SimpleNamespace(
        initialize=Mock(return_value=True), shutdown=Mock(),
        terminal_info=Mock(return_value=SimpleNamespace(path=str(other), connected=True)),
    )
    proxy = reader.ReadOnlySDK(sdk, terminal)
    with pytest.raises(RuntimeError, match="identity"):
        proxy.initialize(str(terminal))
    sdk.shutdown.assert_called_once()


def config_file(tmp_path, terminal, extra=""):
    path = tmp_path / "reader.toml"
    path.write_text(
        "[mt5]\nterminal_path = " + repr(str(terminal)) + "\n"
        "[audit]\npath = " + repr(str(tmp_path / "audit.jsonl")) + "\n"
        "[idempotency]\npath = " + repr(str(tmp_path / "state.db")) + "\n" + extra,
        encoding="utf-8",
    )
    return path


def test_explicit_private_config_accepts_only_existing_terminal(reader, terminal, tmp_path):
    path = config_file(tmp_path, terminal)
    assert reader.validated_terminal(path, {}) == terminal


@pytest.mark.parametrize("name", ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"])
def test_credentials_cannot_override_existing_session(reader, terminal, tmp_path, name):
    path = config_file(tmp_path, terminal)
    with pytest.raises(ValueError, match="overrides"):
        reader.validated_terminal(path, {name: "not-a-real-credential"})


@pytest.mark.parametrize("setting", [
    'enabled = true\nendpoint = ""',
    'enabled = false\nendpoint = "https://example.invalid/telemetry"',
])
def test_telemetry_configuration_is_refused(reader, terminal, tmp_path, setting):
    path = config_file(tmp_path, terminal, "[telemetry]\n" + setting + "\n")
    with pytest.raises(ValueError, match="Telemetry"):
        reader.validated_terminal(path, {})


def test_missing_state_paths_does_not_fall_back_to_user_profile(reader, terminal, tmp_path):
    path = tmp_path / "reader.toml"
    path.write_text("[mt5]\nterminal_path = " + repr(str(terminal)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="audit.path"):
        reader.validated_terminal(path, {})


def test_cleanup_releases_own_worker_resources(reader):
    calls = []
    context = SimpleNamespace(
        poller=SimpleNamespace(stop=lambda: calls.append("poller")),
        config_watcher=SimpleNamespace(stop=lambda: calls.append("watcher")),
        client=SimpleNamespace(disconnect=lambda: calls.append("ipc")),
        policy=SimpleNamespace(close=lambda: calls.append("state")),
    )
    reader.close_context(context)
    assert calls == ["poller", "watcher", "ipc", "state"]
