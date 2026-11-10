"""Exact, closed-candle market structure; no SDK, model or network dependencies."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from itertools import pairwise

TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                     "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}


def _price(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Prices must be bounded decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal price") from exc
    if (not number.is_finite() or number <= 0 or len(number.as_tuple().digits) > 32
            or not -12 <= number.as_tuple().exponent <= 12):
        raise ValueError("Invalid or out-of-range price")
    return number


def _utc(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")
    return stamp.astimezone(UTC)


def sequence_structure(values, *, required=3):
    """Strict inequalities only; equality cannot become a higher high/low."""
    if type(required) is not int or not 3 <= required <= 10:
        raise ValueError("Require 3-10 observations")
    prices = [_price(value) for value in values]
    with localcontext() as ctx:
        ctx.prec = 64
        changes = [b - a for a, b in pairwise(prices)]
    comparisons = ["up" if d > 0 else "down" if d < 0 else "equal" for d in changes]
    direction = "mixed"
    if len(prices) < required:
        direction = "insufficient"
    elif all(d > 0 for d in changes):
        direction = "rising"
    elif all(d < 0 for d in changes):
        direction = "falling"
    elif all(d == 0 for d in changes):
        direction = "flat"
    elif all(d >= 0 for d in changes):
        direction = "non_decreasing"
    elif all(d <= 0 for d in changes):
        direction = "non_increasing"
    return {"values": values, "comparisons": comparisons,
            "changes": [format(d, "f") for d in changes], "direction": direction,
            "strictly_rising": direction == "rising", "strictly_falling": direction == "falling"}


def _combined(highs, lows):
    a, b = highs["direction"], lows["direction"]
    if "insufficient" in (a, b):
        return "insufficient"
    return a if a == b and a in {"rising", "falling", "flat"} else "mixed"


def _series(points, field, required):
    result = sequence_structure([b[field] for b in points], required=required)
    result["times_utc"] = [b["time"] for b in points]
    return result


def _swings(bars, span):
    highs, lows = [], []
    for i in range(span, len(bars) - span):
        center = bars[i]
        neighbors = bars[i - span:i] + bars[i + 1:i + span + 1]
        if all(_price(center["high"]) > _price(b["high"]) for b in neighbors):
            highs.append(center)
        if all(_price(center["low"]) < _price(b["low"]) for b in neighbors):
            lows.append(center)
    return highs, lows


def summarize_structure(bars, *, symbol, timeframe, quote, observed_at_utc,
                        read_started_utc, sequence_bars=3, swing_span=2):
    """Return reproducible evidence, without claiming a forecast or a proven trend."""
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError("Use a supported fixed-duration timeframe; MN1 requires calendar boundaries")
    if (type(sequence_bars) is not int or not 3 <= sequence_bars <= 10
            or type(swing_span) is not int or not 1 <= swing_span <= 5):
        raise ValueError("Invalid sequence size or swing span")
    if not isinstance(bars, list) or not 1 <= len(bars) <= 500:
        raise ValueError("Expected 1-500 broker candles")
    observed, started, tick = map(_utc, (observed_at_utc, read_started_utc, quote["time"]))
    if started > observed or (observed - started).total_seconds() > 30:
        raise ValueError("Market read is not a bounded coherent snapshot")
    age = (observed - tick).total_seconds()
    if not -5 <= age <= 120:
        raise ValueError("Stale or future quote; no current structure verdict")
    if quote.get("symbol") != symbol:
        raise ValueError("Quote symbol does not match")
    bid, ask = _price(quote["bid"]), _price(quote["ask"])
    if ask < bid:
        raise ValueError("Ask is below bid")
    ordered = sorted(bars, key=lambda b: _utc(b["time"]))
    timestamps = [_utc(b["time"]) for b in ordered]
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("Duplicate candle timestamps")
    for bar, stamp in zip(ordered, timestamps):
        o, h, low, c = (_price(bar[k]) for k in ("open", "high", "low", "close"))
        if not low <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Invalid candle OHLC bounds")
        if stamp > observed + timedelta(seconds=5):
            raise ValueError("Future candle timestamp")
    # Conservatively freeze closure BEFORE fetching: a bar closing during the read
    # must not be treated as complete from a pre-close OHLC snapshot.
    cutoff = min(started, tick)
    duration = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    closed = [b for b, t in zip(ordered, timestamps) if t + duration <= cutoff]
    recent = closed[-sequence_bars:]
    highs, lows = _series(recent, "high", sequence_bars), _series(recent, "low", sequence_bars)
    swing_highs, swing_lows = _swings(closed, swing_span)
    sh = _series(swing_highs[-sequence_bars:], "high", sequence_bars)
    sl = _series(swing_lows[-sequence_bars:], "low", sequence_bars)
    last = closed[-1] if closed else None
    with localcontext() as ctx:
        ctx.prec = 64
        spread = format(ask - bid, "f")
    return {"schema": "meu.mt5.market-structure.v1",
            "validation": {"status": "passed", "arithmetic": "Decimal", "precision_digits": 64},
            "scope": {"symbol": symbol, "timeframe": timeframe, "observed_at_utc": observed.isoformat(),
                      "closed_bar_cutoff_utc": cutoff.isoformat(), "sequence_bars": sequence_bars,
                      "swing_span_each_side": swing_span},
            "quote": {**quote, "age_seconds_at_read": age, "spread_price": spread},
            "candles": {"received": len(ordered), "closed": len(closed),
                        "forming_or_after_cutoff_excluded": len(ordered) - len(closed),
                        "last_closed": last,
                        "last_closed_end_utc": (_utc(last["time"]) + duration).isoformat() if last else None},
            "recent_candle_structure": {"highs": highs, "lows": lows,
                                        "classification": _combined(highs, lows)},
            "confirmed_swing_structure": {"highs": sh, "lows": sl, "classification": _combined(sh, sl),
                                          "high_pivots_found": len(swing_highs), "low_pivots_found": len(swing_lows)},
            "interpretation_limits": [
                "Candle-sequence structure and confirmed swing structure are separate, bounded observations.",
                "Only rising/falling means every comparison is strict; equal/mixed/insufficient never means strict.",
                "Swings use strictly higher/lower prices than all neighbors on each side; plateaus are not pivots.",
                "The latest swing_span closed bars cannot confirm new pivots without right-side closed neighbors.",
                "Do not cherry-pick a subsequence to replace these verdicts or infer a guaranteed price movement.",
                "A geometric classification is not a tested trend strategy or a probability forecast."]}
