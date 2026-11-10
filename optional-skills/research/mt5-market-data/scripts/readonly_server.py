"""Data-only adapter for the pinned community mt5-trading-mcp server."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.metadata
import json
import math
import os
import sys
import tomllib
from pathlib import Path
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

UPSTREAM_VERSION = "1.6.1"
SDK_VERSION = "5.0.6231"
READ_TOOLS = frozenset({
    "ping", "get_terminal_info", "get_account_info", "get_quote", "get_symbols",
    "get_market_hours", "get_rates", "calc_margin", "get_positions", "get_orders",
    "get_history", "get_ea_summary", "get_market_structure",
})
SDK_READS = frozenset({
    "shutdown", "last_error", "version", "terminal_info", "account_info",
    "symbols_get", "symbols_total", "symbol_info", "symbol_info_tick",
    "copy_rates_from", "copy_rates_from_pos", "copy_rates_range",
    "copy_ticks_from", "copy_ticks_range", "orders_get", "orders_total",
    "positions_get", "positions_total", "history_orders_get", "history_orders_total",
    "history_deals_get", "history_deals_total", "order_calc_margin",
})


def validated_terminal(config_path, environ=None):
    """Attach only to the configured terminal and its existing broker session."""
    env = os.environ if environ is None else environ
    if any(env.get(name) for name in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER")):
        raise ValueError("The reader does not accept broker-login environment overrides")
    data = tomllib.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    section = data.get("mt5", {})
    if any(section.get(name) is not None for name in ("login", "server", "bridge")):
        raise ValueError("Use the existing native terminal session, without login or bridge settings")
    terminal = Path(section.get("terminal_path", "")).resolve(strict=True)
    if not terminal.is_file() or terminal.name.lower() != "terminal64.exe":
        raise ValueError("An explicit existing terminal64.exe is required")
    telemetry = data.get("telemetry", {})
    if telemetry.get("enabled", False) is not False or telemetry.get("endpoint", ""):
        raise ValueError("Telemetry must be disabled with an empty endpoint")
    for name in ("audit", "idempotency"):
        value = data.get(name, {}).get("path")
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"Choose an explicit local {name}.path")
    return terminal


class ReadOnlySDK:
    """Limit the SDK surface as well as the MCP registry; not a Python sandbox."""

    def __init__(self, module, terminal):
        self._module = module
        self._terminal = Path(terminal).resolve(strict=True)

    def initialize(self, *args, **kwargs):
        if len(args) != 1 or Path(args[0]).resolve() != self._terminal:
            raise PermissionError("Only the configured terminal can be initialized")
        if set(kwargs) - {"timeout"}:
            raise PermissionError("Broker login and terminal-mode overrides are disabled")
        ok = self._module.initialize(str(self._terminal), timeout=10000)
        if not ok:
            return False
        info = self._module.terminal_info()
        if info is None or not info.connected or Path(info.path).resolve() != self._terminal.parent:
            self._module.shutdown()
            raise RuntimeError("Selected terminal identity or connection could not be verified")
        return True

    def __getattr__(self, name):
        if name in SDK_READS:
            return getattr(self._module, name)
        if name.isupper() and not name.startswith("_"):
            value = getattr(self._module, name)
            if isinstance(value, (int, float, str, bool)):
                return value
        raise PermissionError(f"MT5 operation is unavailable in the data-only reader: {name}")


async def keep_read_tools(server):
    """Remove unknown and mutating tools before the protocol starts."""
    for tool in await server.list_tools():
        if tool.name not in READ_TOOLS:
            server.remove_tool(tool.name)
    remaining = {tool.name for tool in await server.list_tools()}
    if remaining != READ_TOOLS:
        raise RuntimeError("The pinned upstream read-tool contract has changed")
    return sorted(remaining)


def read_ea_positions(client, convert, symbol=None, magic=None):
    """Keep broker identity fields; comments are not reliable EA identifiers."""
    rows = client.call(lambda sdk: sdk.positions_get(**({"symbol": symbol} if symbol else {})))
    if rows is None:
        raise RuntimeError("MT5 positions query failed; check the terminal connection")
    result = []
    for raw in rows:
        if symbol is not None and raw.symbol != symbol:
            continue
        if magic is not None and raw.magic != magic:
            continue
        item = convert(raw, broker_offset_minutes=client.broker_offset_minutes).model_dump(mode="json")
        item.update(magic=raw.magic, identifier=raw.identifier, reason=raw.reason)
        result.append(item)
    return result


def _utc_bound(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("History timestamps must include a timezone")
    return parsed.astimezone(UTC)


def read_ea_history(client, convert, from_ts, to_ts, symbol=None, magic=None, position_id=None):
    """Query and filter on the same clock, independent of Windows' local timezone."""
    start, end = _utc_bound(from_ts), _utc_bound(to_ts)
    if end <= start:
        raise ValueError("to_ts must be strictly after from_ts")

    def query(sdk):
        # Upstream normalises this terminal's broker-encoded epochs with this offset.
        # Integer bounds avoid the SDK's host-local interpretation of naive datetimes.
        shift = timedelta(minutes=client.broker_offset_minutes)
        return sdk.history_deals_get(math.floor((start + shift).timestamp()),
                                     math.ceil((end + shift).timestamp()))

    rows = client.call(query)
    if rows is None:
        raise RuntimeError("MT5 history query failed; check the terminal connection")
    offset = client.broker_offset_minutes
    result = []
    for raw in rows:
        if symbol is not None and raw.symbol != symbol:
            continue
        if magic is not None and raw.magic != magic:
            continue
        if position_id is not None and raw.position_id != position_id:
            continue
        stamp = getattr(raw, "time_msc", 0) or raw.time * 1000
        instant = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=stamp, minutes=-offset)
        if not start <= instant <= end:
            continue
        item = convert(raw, broker_offset_minutes=offset).model_dump(mode="json")
        item.update(magic=raw.magic, position_id=raw.position_id, entry_code=raw.entry,
                    entry={0: "in", 1: "out", 2: "inout", 3: "out_by"}.get(raw.entry, "unknown"),
                    reason=raw.reason, type_code=raw.type, time_msc=stamp - offset * 60000,
                    fee=format(Decimal(str(raw.fee)), "f"))
        result.append(item)
    return result


def read_ea_summary(client, position_convert, deal_convert, from_ts, to_ts, magic, symbol=None):
    """Read a stable exposure snapshot, then compute the receipt before model inference."""
    from ea_metrics import summarize_ea

    before = read_ea_positions(client, position_convert, symbol=symbol, magic=magic)
    history = read_ea_history(client, deal_convert, from_ts, to_ts, symbol=symbol, magic=magic)
    after = read_ea_positions(client, position_convert, symbol=symbol, magic=magic)
    fields = ("identifier", "magic", "symbol", "type", "volume")
    first = sorted(tuple(p[k] for k in fields) for p in before)
    last = sorted(tuple(p[k] for k in fields) for p in after)
    if first != last:
        raise RuntimeError("EA exposure changed during the read; retry the summary with a fresh snapshot")
    return summarize_ea(history, after, from_ts=from_ts, to_ts=to_ts, magic=magic,
                        symbol=symbol, positions_at_utc=datetime.now(UTC).isoformat())


def read_market_structure(context, bar_convert, quote_convert, symbol, timeframe, count=120):
    """Read only quote/candles and compute structure before the model sees it."""
    from market_structure import TIMEFRAME_SECONDS, summarize_structure

    if timeframe not in TIMEFRAME_SECONDS or type(count) is not int or not 10 <= count <= 500:
        raise ValueError("Use a fixed-duration timeframe and count between 10 and 500")
    started = datetime.now(UTC).isoformat()
    context.symbols.get(symbol)  # The SDK guard refuses enabling hidden symbols.

    def query(sdk):
        rows = sdk.copy_rates_from_pos(symbol, getattr(sdk, "TIMEFRAME_" + timeframe), 0, count)
        tick = sdk.symbol_info_tick(symbol)
        return rows, tick

    rows, tick = context.client.call(query)
    if rows is None or tick is None:
        raise RuntimeError("MT5 market query failed; not an empty or verified structure")
    offset = context.client.broker_offset_minutes
    bars = [bar_convert(row, broker_offset_minutes=offset).model_dump(mode="json") for row in rows]
    quote = quote_convert(tick, symbol=symbol, broker_offset_minutes=offset).model_dump(mode="json")
    return summarize_structure(bars, symbol=symbol, timeframe=timeframe, quote=quote,
                               read_started_utc=started, observed_at_utc=datetime.now(UTC).isoformat())


def install_market_reader(server, context):
    from mt5_mcp.adapter.conversions import quote_from_tick, rate_from_raw
    from mt5_mcp.tools._common import error_envelope
    from mcp.types import ToolAnnotations

    @error_envelope
    def get_market_structure(symbol: str, timeframe: str, count: int = 120) -> dict[str, Any]:
        """Verified closed-candle highs/lows and confirmed swings. Use BEFORE trend labels.

        Strict/equal/mixed/insufficient sequences are computed with Decimal; quote must be fresh.
        Current candles never confirm structure. This is geometric evidence, not a forecast.
        """
        return read_market_structure(context, rate_from_raw, quote_from_tick, symbol, timeframe, count)

    server.add_tool(get_market_structure, name="get_market_structure", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))


def install_ea_readers(server, context):
    """Replace only the two read handlers; extend the read schemas while retaining the SDK guard."""
    from mt5_mcp.adapter.conversions import deal_from_raw, position_from_raw
    from mt5_mcp.tools._common import error_envelope
    from mcp.types import ToolAnnotations

    @error_envelope
    def get_positions(symbol: str | None = None, magic: int | None = None) -> list[dict[str, Any]]:
        """Open positions with magic, identifier and reason; optional exact symbol/magic filters."""
        return read_ea_positions(context.client, position_from_raw, symbol=symbol, magic=magic)

    @error_envelope
    def get_history(from_ts: str, to_ts: str, symbol: str | None = None,
                    magic: int | None = None, position_id: int | None = None) -> list[dict[str, Any]]:
        """Deals within an inclusive timezone-aware interval, including entry/exit, magic and position_id.

        Entry/exit records are not automatically complete trades. Filters combine with AND.
        For manual exits with a different magic, query the known position_id without a magic filter.
        """
        return read_ea_history(context.client, deal_from_raw, from_ts, to_ts,
                               symbol=symbol, magic=magic, position_id=position_id)

    @error_envelope
    def get_ea_summary(from_ts: str, to_ts: str, magic: int, symbol: str | None = None) -> dict[str, Any]:
        """Verified Decimal EA accounting. Use BEFORE interpreting an EA's performance.

        Separates deals from complete trades, incomplete positions, costs and floating P/L.
        All numeric claims must use this receipt; do not recount raw get_history records.
        Direction win/loss counts and payoff means/ratios are computed, not inferred from net.
        Use the code-built descriptive_report for factual prose; no extra inferred arithmetic.
        Findings describe this sample only; no EA mechanism or future performance is validated.
        A failed validation is an error, never a verified empty summary. Read only.
        """
        return read_ea_summary(context.client, position_from_raw, deal_from_raw,
                               from_ts, to_ts, magic=magic, symbol=symbol)

    server.add_tool(get_ea_summary, name="get_ea_summary", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))

    for name, handler in (("get_positions", get_positions), ("get_history", get_history)):
        server.remove_tool(name)
        server.add_tool(handler, name=name, annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))


def check_versions():
    expected = {"mt5-trading-mcp": UPSTREAM_VERSION, "MetaTrader5": SDK_VERSION}
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise RuntimeError(f"Expected the reviewed {package} version {version}")
    if not importlib.metadata.version("mcp").startswith("1."):
        raise RuntimeError("Use the isolated MCP 1.x environment; do not downgrade Meu's MCP SDK")


def close_context(context):
    context.poller.stop()
    if context.config_watcher is not None:
        context.config_watcher.stop()
    context.client.disconnect()
    context.policy.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Meu MT5 data-only MCP server")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Verify terminal and tool names, then exit")
    args = parser.parse_args(argv)
    context = None
    try:
        terminal = validated_terminal(args.config)
        check_versions()
        sdk = ReadOnlySDK(importlib.import_module("MetaTrader5"), terminal)
        from mt5_mcp.server import build_server, get_context
        server = build_server(config_path=args.config, mt5_module=sdk, log_level="WARNING")
        context = get_context()
        install_ea_readers(server, context)
        install_market_reader(server, context)
        tools = asyncio.run(keep_read_tools(server))
        context.client.connect()
        if args.check:
            print(json.dumps({"ok": True, "read_only": True, "terminal": str(terminal),
                              "tools": tools, "upstream_version": UPSTREAM_VERSION,
                              "telemetry": False}))
        else:
            print("Meu MT5: verified terminal; data-only tools; stdio transport.", file=sys.stderr)
            server.run(transport="stdio")
        return 0
    except (ValueError, OSError, RuntimeError, importlib.metadata.PackageNotFoundError) as exc:
        print(f"Meu MT5 reader: {exc}", file=sys.stderr)
        return 1
    finally:
        if context is not None:
            close_context(context)


if __name__ == "__main__":
    raise SystemExit(main())
