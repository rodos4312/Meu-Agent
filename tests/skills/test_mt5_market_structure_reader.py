"""The market-structure MCP handler reads broker data without account/mutation APIs."""
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "optional-skills/research/mt5-market-data/scripts/readonly_server.py"


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("meu_structure_reader_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reader_computes_geometry_with_the_post_connect_broker_offset(reader):
    now = datetime.now(UTC)
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    bars = [{"time": (start + timedelta(minutes=15 * i)).isoformat(), "open": str(5 + i),
             "high": str(10 + i), "low": str(5 + i), "close": str(6 + i)} for i in range(3)]
    sdk = SimpleNamespace(TIMEFRAME_M15=15, copy_rates_from_pos=Mock(return_value=bars),
                          symbol_info_tick=Mock(return_value="tick"))
    client = SimpleNamespace(broker_offset_minutes=0)

    def connected(fn):
        client.broker_offset_minutes = 120
        return fn(sdk)

    client.call = connected
    context = SimpleNamespace(client=client, symbols=SimpleNamespace(get=Mock()))
    convert_bar = Mock(side_effect=lambda row, **kw: SimpleNamespace(model_dump=lambda **kw: row))
    quote = {"symbol": "XAUUSD", "bid": "10", "ask": "10.39", "time": now.isoformat()}
    convert_quote = Mock(return_value=SimpleNamespace(model_dump=lambda **kw: quote))
    result = reader.read_market_structure(context, convert_bar, convert_quote, "XAUUSD", "M15", 120)
    assert result["recent_candle_structure"]["classification"] == "rising"
    assert result["quote"]["spread_price"] == "0.39"
    sdk.copy_rates_from_pos.assert_called_once_with("XAUUSD", 15, 0, 120)
    context.symbols.get.assert_called_once_with("XAUUSD")
    assert all(call.kwargs["broker_offset_minutes"] == 120 for call in convert_bar.call_args_list)
    convert_quote.assert_called_once_with("tick", symbol="XAUUSD", broker_offset_minutes=120)


def test_bad_request_does_not_reach_sdk(reader):
    context = SimpleNamespace(symbols=SimpleNamespace(get=Mock()), client=Mock())
    for tf, count in (("MN1", 120), ("H1", 0), ("H1", True), ("H1", 501)):
        with pytest.raises(ValueError):
            reader.read_market_structure(context, Mock(), Mock(), "XAUUSD", tf, count)
    context.symbols.get.assert_not_called()
    context.client.call.assert_not_called()


def test_failed_sdk_read_is_not_an_empty_verified_market(reader):
    client = SimpleNamespace(call=lambda fn: (None, None))
    context = SimpleNamespace(client=client, symbols=SimpleNamespace(get=Mock()))
    with pytest.raises(RuntimeError, match="failed"):
        reader.read_market_structure(context, Mock(), Mock(), "XAUUSD", "H1")
