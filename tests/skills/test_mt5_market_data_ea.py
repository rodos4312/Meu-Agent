"""EA identity and history-window contracts, without a live terminal or SDK."""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "optional-skills/research/mt5-market-data/scripts/readonly_server.py"


@pytest.fixture
def reader():
    spec = importlib.util.spec_from_file_location("meu_mt5_ea_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def client_with(**methods):
    sdk = SimpleNamespace(**methods)
    return SimpleNamespace(broker_offset_minutes=120, call=lambda fn: fn(sdk))


def converter(raw, *, broker_offset_minutes):
    return SimpleNamespace(model_dump=lambda **kw: {"comment": raw.comment, "volume": "0.03"})


def deal(epoch, magic=151515, symbol="XAUUSD", *, entry=0, msec=0):
    return SimpleNamespace(time=epoch, time_msc=epoch * 1000 + msec, magic=magic,
                           symbol=symbol, position_id=22, entry=entry, reason=3,
                           type=0, fee=-0.1, comment="")


def test_positions_keep_ea_identity_and_magic_zero_is_a_real_filter(reader):
    rows = [SimpleNamespace(magic=m, identifier=22 + i, symbol="XAUUSD", reason=3,
                            comment="same comment") for i, m in enumerate([0, 151515, 999])]
    sdk_read = Mock(return_value=rows)
    client = client_with(positions_get=sdk_read)
    result = reader.read_ea_positions(client, converter, magic=0)
    assert result == [{"comment": "same comment", "volume": "0.03", "magic": 0,
                       "identifier": 22, "reason": 3}]
    sdk_read.assert_called_once_with()
    result = reader.read_ea_positions(client, converter, symbol="XAUUSD", magic=151515)
    assert len(result) == 1 and result[0]["identifier"] == 23
    sdk_read.assert_called_with(symbol="XAUUSD")


def test_history_uses_broker_epoch_and_rejects_outside_window(reader):
    start = datetime(2026, 11, 10, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    epoch = int(start.timestamp()) + 7200
    rows = [deal(epoch - 1), deal(epoch), deal(epoch + 3600, entry=1),
            deal(epoch + 3601), deal(epoch + 20, magic=999), deal(epoch + 30, symbol="XAUUSD.a")]
    sdk_read = Mock(return_value=rows)
    convert = Mock(side_effect=converter)
    result = reader.read_ea_history(client_with(history_deals_get=sdk_read), convert,
                                    start.isoformat(), end.isoformat(), symbol="XAUUSD", magic=151515)
    sdk_read.assert_called_once_with(epoch, epoch + 3600)
    assert [r["entry"] for r in result] == ["in", "out"]
    assert [r["time_msc"] for r in result] == [int(start.timestamp()) * 1000, int(end.timestamp()) * 1000]
    assert all(r["position_id"] == 22 and r["magic"] == 151515 and r["fee"] == "-0.1" for r in result)
    assert convert.call_count == 2
    assert all(c.kwargs["broker_offset_minutes"] == 120 for c in convert.call_args_list)


def test_fractional_window_and_explicit_timezone_are_respected(reader):
    start = datetime(2026, 11, 10, 2, 0, 0, 500000, tzinfo=timezone(timedelta(hours=2)))
    end = start + timedelta(milliseconds=500)
    epoch = int(start.timestamp()) + 7200
    rows = [deal(epoch, msec=499), deal(epoch, msec=500), deal(epoch + 1), deal(epoch + 1, msec=1)]
    sdk_read = Mock(return_value=rows)
    result = reader.read_ea_history(client_with(history_deals_get=sdk_read), converter,
                                    start.isoformat(), end.isoformat())
    sdk_read.assert_called_once_with(epoch, epoch + 1)
    assert [x["time_msc"] for x in result] == [int(start.timestamp() * 1000), int(end.timestamp() * 1000)]


def test_position_filter_can_include_manual_exit_without_claiming_ea_magic(reader):
    start = datetime(2026, 11, 10, tzinfo=UTC)
    epoch = int(start.timestamp()) + 7200
    rows = [deal(epoch + 1), deal(epoch + 2, magic=0, entry=1), deal(epoch + 3, magic=999)]
    rows[2].position_id = 33
    result = reader.read_ea_history(client_with(history_deals_get=Mock(return_value=rows)), converter,
                                    start.isoformat(), (start + timedelta(minutes=1)).isoformat(), position_id=22)
    assert [r["magic"] for r in result] == [151515, 0]
    assert result[1]["entry_code"] == 1


def test_unknown_entry_is_retained_without_inventing_closed_trade(reader):
    start = datetime(2026, 11, 10, tzinfo=UTC)
    row = deal(int(start.timestamp()) + 7201, entry=99)
    result = reader.read_ea_history(client_with(history_deals_get=Mock(return_value=[row])), converter,
                                    start.isoformat(), (start + timedelta(minutes=1)).isoformat())
    assert result[0]["entry"] == "unknown" and result[0]["entry_code"] == 99


@pytest.mark.parametrize("start,end", [
    ("2026-11-10T00:00:00", "2026-11-10T01:00:00Z"),
    ("2026-11-10T01:00:00Z", "2026-11-10T00:00:00Z"),
    ("2026-11-10T00:00:00Z", "2026-11-10T00:00:00Z"),
    ("invalid", "2026-11-10T00:00:00Z"),
])
def test_invalid_interval_fails_before_query(reader, start, end):
    call = Mock()
    with pytest.raises(ValueError):
        reader.read_ea_history(SimpleNamespace(call=call), converter, start, end)
    call.assert_not_called()


@pytest.mark.parametrize("family", ["positions", "history"])
def test_sdk_failure_is_not_reported_as_an_empty_account(reader, family):
    client = client_with(positions_get=Mock(return_value=None), history_deals_get=Mock(return_value=None))
    with pytest.raises(RuntimeError, match="failed"):
        if family == "positions":
            reader.read_ea_positions(client, converter)
        else:
            reader.read_ea_history(client, converter, "2026-11-10T00:00:00Z", "2026-11-10T01:00:00Z")


def test_utc_encoded_terminal_needs_no_shift(reader):
    start = datetime(2026, 11, 10, tzinfo=UTC)
    epoch = int(start.timestamp())
    read = Mock(return_value=[deal(epoch + 1)])
    client = client_with(history_deals_get=read)
    client.broker_offset_minutes = 0
    result = reader.read_ea_history(client, converter, start.isoformat(),
                                    (start + timedelta(seconds=2)).isoformat())
    read.assert_called_once_with(epoch, epoch + 2)
    assert result[0]["time_msc"] == (epoch + 1) * 1000


def test_reconnect_offset_is_read_inside_the_sdk_query(reader):
    start = datetime(2026, 11, 10, tzinfo=UTC)
    epoch = int(start.timestamp())
    read = Mock(return_value=[deal(epoch + 10801)])
    client = SimpleNamespace(broker_offset_minutes=120)

    def reconnect_then_call(fn):
        client.broker_offset_minutes = 180
        return fn(SimpleNamespace(history_deals_get=read))

    client.call = reconnect_then_call
    result = reader.read_ea_history(client, converter, start.isoformat(),
                                    (start + timedelta(seconds=2)).isoformat())
    read.assert_called_once_with(epoch + 10800, epoch + 10802)
    assert result[0]["time_msc"] == (epoch + 1) * 1000


def test_summary_refuses_exposure_changed_while_reading(reader, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    row = {"identifier": 22, "magic": 151515, "symbol": "XAUUSD", "type": "buy", "volume": "0.03"}
    monkeypatch.setattr(reader, "read_ea_positions", Mock(side_effect=[[row], [dict(row, volume="0.02")]]))
    monkeypatch.setattr(reader, "read_ea_history", Mock(return_value=[]))
    with pytest.raises(RuntimeError, match="exposure changed"):
        reader.read_ea_summary(object(), converter, converter, "2026-11-10T00:00:00Z",
                               "2026-11-10T01:00:00Z", magic=151515)


def test_summary_stable_empty_snapshot_is_computed_before_return(reader, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    positions = Mock(side_effect=[[], []]); history = Mock(return_value=[])
    monkeypatch.setattr(reader, "read_ea_positions", positions)
    monkeypatch.setattr(reader, "read_ea_history", history)
    result = reader.read_ea_summary(object(), converter, converter, "2026-11-10T00:00:00Z",
                                    "2026-11-10T01:00:00Z", magic=151515)
    assert positions.call_count == 2
    assert result["validation"]["status"] == "passed"
    assert result["reconciliation"]["difference"] == "0"
    assert history.call_args.kwargs["magic"] == 151515
