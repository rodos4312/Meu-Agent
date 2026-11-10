"""Exact, local EA accounting. No SDK, network, model, or broker mutations."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

MONEY = ("profit", "swap", "commission", "fee")
ENTRY = {0: "in", 1: "out", 2: "inout", 3: "out_by"}
REASONS = {0: "desktop_client", 1: "mobile_client", 2: "web_client", 3: "expert",
           4: "stop_loss", 5: "take_profit", 6: "stop_out"}
STATUSES = ("complete", "entry_only", "exit_only", "partial_or_incomplete", "ambiguous")


def _decimal(row, field, *, positive=False):
    value = row.get(field)
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError(f"{field} must be an explicit decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {field}") from exc
    if not number.is_finite() or len(number.as_tuple().digits) > 40 or abs(number.as_tuple().exponent) > 20:
        raise ValueError(f"Invalid or excessive {field}")
    if positive and number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


def _integer(row, field, *, minimum=0):
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"Invalid {field}")
    return value


def _text(number):
    text = format(number, "f")
    if number == 0:
        return "0"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("An explicit timezone is required")
    return parsed.astimezone(UTC)


def _validated_rows(history, start, end, magic, symbol):
    unique = {}
    duplicates = 0
    for source in history:
        ticket = _integer(source, "ticket", minimum=1)
        if ticket in unique:
            if unique[ticket]["source"] != source:
                raise ValueError("Conflicting duplicate deal ticket")
            duplicates += 1
            continue
        if _integer(source, "magic") != magic or (symbol is not None and source.get("symbol") != symbol):
            raise ValueError("Deal outside the requested EA scope")
        stamp = _integer(source, "time_msc")
        if not start <= Decimal(stamp) / 1000 <= end:
            raise ValueError("Deal outside the requested interval")
        amounts = {field: _decimal(source, field) for field in MONEY}
        trade = source.get("type") in ("buy", "sell")
        pid = _integer(source, "position_id", minimum=1 if trade else 0)
        code = _integer(source, "entry_code")
        _integer(source, "reason")
        if source.get("entry") != ENTRY.get(code, "unknown"):
            raise ValueError("Inconsistent deal entry metadata")
        if not isinstance(source.get("symbol"), str) or (trade and not source["symbol"]):
            raise ValueError("Invalid symbol")
        unique[ticket] = {"source": source, "pid": pid, "amounts": amounts,
                          "volume": _decimal(source, "volume", positive=trade),
                          "net": sum(amounts.values(), Decimal(0)), "trade": trade}
    return list(unique.values()), duplicates


def _group(rows, open_ids):
    rows = sorted(rows, key=lambda r: (r["source"]["time_msc"], r["source"]["ticket"]))
    sources = [r["source"] for r in rows]
    ins = [r for r in rows if r["source"]["entry"] == "in"]
    outs = [r for r in rows if r["source"]["entry"] in ("out", "out_by")]
    inv = sum((r["volume"] for r in ins), Decimal(0))
    outv = sum((r["volume"] for r in outs), Decimal(0))
    pid = rows[0]["pid"]
    ambiguous = (len(ins) + len(outs) != len(rows) or len({s["symbol"] for s in sources}) != 1
                 or len({r["source"]["type"] for r in ins}) > 1
                 or len({r["source"]["type"] for r in outs}) > 1
                 or bool(ins and any(r["source"]["type"] == ins[0]["source"]["type"] for r in outs)))
    if ambiguous:
        status = "ambiguous"
    elif ins and outs and inv == outv and pid not in open_ids and sources[0]["entry"] == "in":
        status = "complete"
    elif ins and not outs:
        status = "entry_only"
    elif outs and not ins:
        status = "exit_only"
    else:
        status = "partial_or_incomplete"
    net = sum((r["net"] for r in rows), Decimal(0))
    return {"position_id": pid, "symbol": sources[0]["symbol"], "status": status,
            "direction": ins[0]["source"]["type"] if ins else
                         {"buy": "sell", "sell": "buy"}.get(outs[0]["source"]["type"]) if outs else None,
            "entry_deals": len(ins), "exit_deals": len(outs), "currently_open": pid in open_ids,
            "entry_volume": _text(inv), "exit_volume": _text(outv), "remaining_volume": _text(inv - outv),
            "partial_exits": len(outs) > 1 or (bool(ins and outs) and 0 < outv < inv),
            "net": _text(net), "start_msc": ins[0]["source"]["time_msc"] if ins else None,
            "end_msc": outs[-1]["source"]["time_msc"] if outs else None,
            "hold_minutes": _text(Decimal(outs[-1]["source"]["time_msc"] - ins[0]["source"]["time_msc"]) / 60000)
            if status == "complete" else None,
            "exit_reason_codes": [r["source"]["reason"] for r in outs]}


def _open_snapshot(positions, magic, symbol):
    unique = {}
    for row in positions:
        ident = _integer(row, "identifier", minimum=1)
        if ident in unique and unique[ident] != row:
            raise ValueError("Conflicting open-position identifier")
        if _integer(row, "magic") != magic or (symbol is not None and row.get("symbol") != symbol):
            raise ValueError("Open position outside the requested EA scope")
        if row.get("type") not in ("buy", "sell") or not isinstance(row.get("symbol"), str) or not row["symbol"]:
            raise ValueError("Invalid open-position direction or symbol")
        _decimal(row, "volume", positive=True)
        unique[ident] = row
    by_symbol = defaultdict(lambda: {"buy_lots": Decimal(0), "sell_lots": Decimal(0), "positions": 0})
    profit = swap = Decimal(0)
    for row in unique.values():
        item = by_symbol[row["symbol"]]
        item[row["type"] + "_lots"] += _decimal(row, "volume", positive=True)
        item["positions"] += 1
        profit += _decimal(row, "profit")
        swap += _decimal(row, "swap")
    return set(unique), {"count": len(unique), "profit": _text(profit), "swap": _text(swap),
                         "floating_excluding_fees": _text(profit + swap),
                         "by_symbol": {s: {k: _text(v) if isinstance(v, Decimal) else v for k, v in values.items()}
                                       for s, values in by_symbol.items()}}


def _rounded(number, places):
    rounded = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)
    return _text(number if number and not rounded else rounded)


def _outcome_stats(values):
    """Use position net AFTER all known costs; a side's net is not its win count."""
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    gains, loss_abs = sum(wins, Decimal(0)), -sum(losses, Decimal(0))
    count = len(values)
    average_win = gains / len(wins) if wins else None
    average_loss = loss_abs / len(losses) if losses else None
    mix = "mixed"
    if not count:
        mix = "no_trades"
    elif len(wins) == count:
        mix = "all_wins"
    elif len(losses) == count:
        mix = "all_losses"
    elif not wins and not losses:
        mix = "breakeven_only"
    return {"count": count, "wins": len(wins), "losses": len(losses),
            "breakeven": count - len(wins) - len(losses), "net": _text(sum(values, Decimal(0))),
            "gross_positive_net": _text(gains), "gross_negative_net_abs": _text(loss_abs),
            "win_rate_percent": format((Decimal(len(wins)) * 100 / count).quantize(Decimal("0.01")), "f") if count else None,
            "profit_factor": format((gains / loss_abs).quantize(Decimal("0.01")), "f") if loss_abs else None,
            "average_win_net": _rounded(average_win, 8) if average_win is not None else None,
            "average_loss_net_abs": _rounded(average_loss, 8) if average_loss is not None else None,
            "average_net_per_position": _rounded(sum(values, Decimal(0)) / count, 8) if count else None,
            "average_win_to_average_loss_ratio": _rounded(average_win / average_loss, 4) if wins and losses else None,
            "average_wins_to_cover_average_loss": _rounded(average_loss / average_win, 4) if wins and losses else None,
            "outcome_mix": mix}


def _complete_stats(groups):
    complete = [g for g in groups if g["status"] == "complete"]
    return {**_outcome_stats([Decimal(g["net"]) for g in complete]),
            "by_direction": {side: _outcome_stats([Decimal(g["net"]) for g in complete if g["direction"] == side])
                             for side in ("buy", "sell")},
            "statistics_scope": "Complete in-window positions only; net includes profit, swap, commission and fee.",
            "rounding": "Averages: 8 decimal places; ratios: 4; half-even. Nonzero values that would round to zero retain precision. Totals remain exact.",
            "ratio_meaning": "average_wins_to_cover_average_loss = abs(mean losing position net) / mean winning position net; a descriptive amount ratio, not a forecast of trades needed."}


def _bounded_conclusions(receipt):
    """Only conclusions whose full predicate is established by the computed counts."""
    stats = receipt["complete_trades"]
    notes = [f"In this window, {stats['count']} complete positions contain {stats['wins']} wins, "
             f"{stats['losses']} losses and {stats['breakeven']} breakevens; their net is {stats['net']}."]
    for side, values in stats["by_direction"].items():
        notes.append(f"{side} in this sample: net {values['net']}, with {values['wins']} winning, "
                     f"{values['losses']} losing and {values['breakeven']} breakeven positions out of "
                     f"{values['count']}. Outcome mix: {values['outcome_mix']}. "
                     "The net total alone does not establish that every position had the same outcome.")
    notes.extend([f"Exit-deal reasons in the complete cohort: {receipt['exit_reasons']}. "
                  "An exit reason is not an outcome; these counts alone do not establish how many SL exits won or lost.",
                  "This is a description of the requested sample only, not evidence of systematic performance, "
                  "EA mechanism, future profitability or a guaranteed closing result."])
    return notes


def _descriptive_report(receipt):
    """Code-built factual backbone; no free-form inference, forecast or account identity."""
    scope, stats = receipt["scope"], receipt["complete_trades"]
    lines = [f"EA magic {scope['magic']}; requested window {scope['from_utc']} to {scope['to_utc']}.",
             "Currency was not queried. Claims apply only to this filtered observation window, not all available history.",
             f"Complete in-window positions: {stats['count']}; wins {stats['wins']}; losses {stats['losses']}; "
             f"breakeven {stats['breakeven']}; net {stats['net']}."]
    for side, values in stats["by_direction"].items():
        lines.append(f"{side} in this sample: {values['count']} positions; {values['wins']} wins; "
                     f"{values['losses']} losses; {values['breakeven']} breakeven; net {values['net']}; "
                     f"outcome mix {values['outcome_mix']}.")
    lines.extend([
        f"Mean winning-position net: {stats['average_win_net']}; mean losing-position net magnitude: "
        f"{stats['average_loss_net_abs']}; mean net per completed position: {stats['average_net_per_position']}.",
        f"Mean-win / mean-loss-magnitude ratio: {stats['average_win_to_average_loss_ratio']}; "
        f"mean-loss-magnitude / mean-win ratio: {stats['average_wins_to_cover_average_loss']}. "
        "Null means undefined. These are observed amount ratios, not a forecast of future trades needed.",
        f"All matching trade-deal net in the window: {receipt['history_totals']['net']}. "
        f"Separate cohort nets: {receipt['net_by_status']}. Do not substitute these for one another.",
        f"Exit-deal reason counts for complete positions: {receipt['exit_reasons']}. "
        "Expert/client exits are not stop-loss exits. A positive SL net alone does not establish how the stop was set or moved.",
        f"Open-position count at snapshot: {receipt['open_positions']['count']}; floating excluding fees: "
        f"{receipt['open_positions']['floating_excluding_fees']}. No assumed closure price, closing costs or future weekly net.",
        "Lots, hold time and observed overlap do not identify the EA mechanism or prove grid/martingale, scalp/swing rules, "
        "stop distance, statistical edge or future profitability."])
    return "\n".join(lines)


def _overlap(groups, start_ms, end_ms):
    if any(g["status"] in ("ambiguous", "partial_or_incomplete") or g["entry_deals"] > 1 or g["exit_deals"] > 1 for g in groups):
        return {"available": False, "reason": "partial_or_ambiguous_lifecycles"}
    events = []
    for g in groups:
        volume = Decimal(g["entry_volume"] if g["entry_deals"] else g["exit_volume"])
        events.extend([(g["start_msc"] if g["start_msc"] is not None else start_ms, 1, g["symbol"], volume),
                       (g["end_msc"] if g["end_msc"] is not None else end_ms, -1, g["symbol"], -volume)])
    if len({e[0] for e in events}) != len(events):
        return {"available": False, "reason": "intra_millisecond_order_ambiguous"}
    count = peak = 0
    lots = defaultdict(Decimal)
    peak_lots = defaultdict(Decimal)
    for _, delta, symbol, volume in sorted(events, key=lambda e: (e[0], e[1])):
        count += delta
        lots[symbol] += volume
        peak = max(peak, count)
        peak_lots[symbol] = max(peak_lots[symbol], lots[symbol])
    return {"available": True, "peak_positions": peak,
            "peak_lots_by_symbol": {s: _text(v) for s, v in peak_lots.items()},
            "boundary_note": "Exit-only groups begin at the interval boundary; entry-only groups extend to its end."}


def summarize_ea(history, positions, *, from_ts, to_ts, magic, symbol=None, positions_at_utc):
    """Return a verified accounting receipt, or refuse invalid/conflicting inputs."""
    if isinstance(magic, bool) or not isinstance(magic, int) or magic < 0:
        raise ValueError("An explicit non-negative magic is required")
    start, end = _utc(from_ts), _utc(to_ts)
    captured = _utc(positions_at_utc)
    if end <= start:
        raise ValueError("Invalid history interval")
    with localcontext() as context:
        context.prec = 100 + len(str(len(history) + len(positions) + 1))
        begin, finish = Decimal(str(start.timestamp())), Decimal(str(end.timestamp()))
        rows, duplicates = _validated_rows(history, begin, finish, magic, symbol)
        open_ids, open_summary = _open_snapshot(positions, magic, symbol)
        trades = [r for r in rows if r["trade"]]
        other = [r for r in rows if not r["trade"]]
        by_id = defaultdict(list)
        for row in trades:
            by_id[row["pid"]].append(row)
        groups = [_group(values, open_ids) for _, values in sorted(by_id.items())]
        counts = Counter(r["source"]["entry"] for r in trades)
        statuses = {status: sum((Decimal(g["net"]) for g in groups if g["status"] == status), Decimal(0)) for status in STATUSES}
        amounts = {field: sum((r["amounts"][field] for r in trades), Decimal(0)) for field in MONEY}
        total = sum(amounts.values(), Decimal(0))
        difference = total - sum(statuses.values(), Decimal(0))
        if difference:
            raise ValueError("Accounting reconciliation failed")
        complete = _complete_stats(groups)
        reasons = Counter(REASONS.get(code, f"unknown_{code}") for g in groups if g["status"] == "complete" for code in g["exit_reason_codes"])
        receipt = {"schema": "meu.mt5.ea-summary.v1", "scope": {"magic": magic, "symbol": symbol,
                 "from_utc": start.isoformat(), "to_utc": end.isoformat(), "positions_at_utc": captured.isoformat(),
                 "currency": "not queried"},
                "validation": {"status": "passed", "arithmetic": "Decimal", "precision_digits": context.prec,
                               "duplicate_records_ignored": duplicates, "group_details_truncated": len(groups) > 50},
                "counts": {"input_records": len(history), "trade_deals": len(trades), "non_trade_records": len(other),
                           "entries": counts["in"], "exits": counts["out"] + counts["out_by"],
                           "reversals": counts["inout"], "unknown_entries": counts["unknown"],
                           "unique_positions": len(groups), "complete_trades": complete["count"],
                           "positions_with_partial_exits": sum(g["partial_exits"] for g in groups),
                           "positions_by_status": {status: sum(g["status"] == status for g in groups) for status in STATUSES}},
                "history_totals": {**{k: _text(v) for k, v in amounts.items()}, "net": _text(total)},
                "non_trade_net_excluded": _text(sum((r["net"] for r in other), Decimal(0))),
                "complete_trades": complete, "net_by_status": {k: _text(v) for k, v in statuses.items()},
                "exit_reasons": dict(reasons), "exit_reasons_scope": "Exit deals of complete in-window lifecycles",
                "open_positions": open_summary,
                "lot_sizes": sorted({_text(r["volume"]) for r in trades}, key=Decimal),
                "overlap": _overlap(groups, begin * 1000, finish * 1000),
                "reconciliation": {"history_net": _text(total), "grouped_net": _text(sum(statuses.values(), Decimal(0))), "difference": "0"},
                "groups": groups[:50],
                "interpretation_limits": ["No inferred account currency; floating P/L excludes opening/closing charges.",
                                          "Only matching magic records are included; shared magic, manual exits and netting can limit attribution.",
                                          "Entry/exit records are not completed trades; ambiguous and incomplete groups stay separate.",
                                          "Amounts are computed by code; do not recount or add floating P/L to history net.",
                                          "Positive directional net does not mean every trade won; use by_direction wins/losses/outcome_mix.",
                                          "Use the supplied averages and ratios; undefined means missing evidence, not zero.",
                                          "All statements concern this observed interval/sample; no statistical generalisation or future edge is validated.",
                                          "Exit reasons include expert/client exits; never call all non-TP exits stop losses unless the counts prove it.",
                                          "Hold times, lots and overlap cannot establish the EA algorithm, SL distance, scalp/swing, grid or martingale mechanism.",
                                          "Floating P/L is an unclosed snapshot with unavailable closing costs; do not project a guaranteed final result."]}
        receipt["bounded_conclusions"] = _bounded_conclusions(receipt)
        receipt["descriptive_report"] = _descriptive_report(receipt)
        return receipt
