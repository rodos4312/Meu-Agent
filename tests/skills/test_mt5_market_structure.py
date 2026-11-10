"""Closed-candle geometry and the real mixed-low regression; no SDK or network."""
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "optional-skills/research/mt5-market-data/scripts/market_structure.py"


@pytest.fixture
def structure():
    spec = importlib.util.spec_from_file_location("meu_market_structure_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bar(i, high, low, close=None):
    return {"time": (datetime(2026, 11, 10, tzinfo=UTC) + timedelta(minutes=15 * i)).isoformat(),
            "high": str(high), "low": str(low), "open": str(close or low), "close": str(close or low)}


def summarize(structure, bars, **overrides):
    kwargs = {"symbol": "XAUUSD", "timeframe": "M15",
              "observed_at_utc": "2026-11-10T03:00:01Z", "read_started_utc": "2026-11-10T03:00:00Z",
              "quote": {"symbol": "XAUUSD", "bid": "4077.03", "ask": "4077.42",
                        "time": "2026-11-10T03:00:00Z"}}
    return structure.summarize_structure(bars, **(kwargs | overrides))


def test_real_mixed_lows_cannot_be_called_higher_lows(structure):
    result = summarize(structure, [bar(0, 4074.19, 4069.32), bar(1, 4078.73, 4073.37),
                                   bar(2, 4078.65, 4073.13)])
    lows = result["recent_candle_structure"]["lows"]
    assert lows["changes"] == ["4.05", "-0.24"]
    assert lows["comparisons"] == ["up", "down"]
    assert lows["direction"] == "mixed" and lows["strictly_rising"] is False
    assert result["recent_candle_structure"]["classification"] == "mixed"


@pytest.mark.parametrize("values,direction", [
    (["1", "2", "3"], "rising"), (["3", "2", "1"], "falling"),
    (["2", "2.0", "2.00"], "flat"), (["1", "1", "2"], "non_decreasing"),
    (["2", "2", "1"], "non_increasing"), (["1", "3", "2"], "mixed"),
    (["1", "2"], "insufficient"), ([], "insufficient"),
])
def test_exact_sequence_labels_and_equal_prices(structure, values, direction):
    result = structure.sequence_structure(values)
    assert result["direction"] == direction
    assert result["strictly_rising"] == (direction == "rising")
    assert result["strictly_falling"] == (direction == "falling")


def test_decimal_comparison_keeps_sub_float_price_changes(structure):
    result = structure.sequence_structure(["4000.000000000001", "4000.000000000002", "4000.000000000003"])
    assert result["direction"] == "rising" and result["changes"] == ["0.000000000001"] * 2


def test_forming_bar_and_bar_closing_during_read_cannot_change_verdict(structure):
    rows = [bar(i, 10 + i, 5 + i) for i in range(3)] + [bar(11, 1, 1), bar(12, 1, 1)]
    result = summarize(structure, rows, read_started_utc="2026-11-10T02:59:59Z")
    assert result["candles"]["closed"] == 3
    assert result["candles"]["forming_or_after_cutoff_excluded"] == 2
    assert result["recent_candle_structure"]["classification"] == "rising"


def test_swings_require_right_side_closed_confirmation(structure):
    # Three rising peaks/troughs; the last extreme has no closed right neighbor.
    highs = [4, 10, 5, 11, 6, 12, 7, 30]
    lows = [3, 4, 2, 5, 3, 6, 4, 20]
    result = summarize(structure, [bar(i, h, low) for i, (h, low) in enumerate(zip(highs, lows))], swing_span=1)
    swings = result["confirmed_swing_structure"]
    assert swings["highs"]["values"] == ["10", "11", "12"]
    assert swings["lows"]["values"] == ["2", "3", "4"]
    assert swings["classification"] == "rising"
    assert "30" not in swings["highs"]["values"]


def test_plateaus_do_not_invent_confirmed_pivots(structure):
    result = summarize(structure, [bar(i, 10, 5) for i in range(8)])
    assert result["recent_candle_structure"]["classification"] == "flat"
    assert result["confirmed_swing_structure"]["classification"] == "insufficient"
    assert result["confirmed_swing_structure"]["high_pivots_found"] == 0


def test_unsorted_broker_rows_are_chronological_without_mutating_input(structure):
    rows = [bar(i, 10 + i, 5 + i) for i in (2, 0, 1)]
    original = list(rows)
    result = summarize(structure, rows)
    assert result["recent_candle_structure"]["highs"]["values"] == ["10", "11", "12"]
    assert rows == original


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "0", "1e1000", "1e-1000", 4077.1])
def test_invalid_price_never_produces_verified_geometry(structure, bad):
    with pytest.raises(ValueError):
        summarize(structure, [bar(0, 10, 5) | {"high": bad}])


def test_invalid_ohlc_and_duplicate_times_are_rejected(structure):
    with pytest.raises(ValueError, match="OHLC"):
        summarize(structure, [bar(0, 4, 5)])
    with pytest.raises(ValueError, match="Duplicate"):
        summarize(structure, [bar(0, 10, 5), bar(0, 11, 6)])


@pytest.mark.parametrize("stamp", ["2026-11-10T02:50:00Z", "2026-11-10T03:01:00Z"])
def test_stale_and_future_ticks_do_not_claim_current_structure(structure, stamp):
    with pytest.raises(ValueError, match="quote"):
        summarize(structure, [bar(0, 10, 5)], quote={"symbol": "XAUUSD", "bid": "10", "ask": "11", "time": stamp})


def test_short_history_is_explicitly_insufficient(structure):
    result = summarize(structure, [bar(0, 10, 5), bar(1, 11, 6)])
    assert result["recent_candle_structure"]["classification"] == "insufficient"
    assert result["confirmed_swing_structure"]["classification"] == "insufficient"


def test_naive_time_calendar_month_wrong_symbol_and_future_bar_fail(structure):
    for kwargs in ({"observed_at_utc": "2026-11-10T03:00:01"}, {"timeframe": "MN1"},
                   {"quote": {"symbol": "EURUSD", "bid": "10", "ask": "11", "time": "2026-11-10T03:00:00Z"}}):
        with pytest.raises(ValueError):
            summarize(structure, [bar(0, 10, 5)], **kwargs)
    with pytest.raises(ValueError, match="Future candle"):
        summarize(structure, [bar(13, 10, 5)])
