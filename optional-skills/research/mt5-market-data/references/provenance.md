# Community source and reviewed adaptation

- Project: https://github.com/vincentwongso/mt5-trading-mcp
- Reviewed source revision: daa905d36135aa1f00017efccc9b39fba7130c3f
- Distribution: mt5-trading-mcp 1.6.1, installed only in the optional worker.
- Original skill: .claude/skills/mt5-market-data/SKILL.md
- Hermes configuration example: examples/clients/hermes.json
- Licence: MIT; retained in LICENSE.upstream.
- SDK: MetaTrader5 5.0.6231, from MetaQuotes' PyPI distribution.

Meu changes: bounded skill metadata, ordinary tool discovery, exact terminal
selection, data-only MCP registry, SDK operation restriction, disabled telemetry,
explicit private state paths and separate dependencies. Meu replaces the positions
and history handlers to preserve EA identity and fix host-local datetime handling.
Upstream value conversions and other read handlers remain upstream implementations.

Not included: trade execution, trading skill, screenshot EA, public HTTP server,
news/Telegram services, automatic account login, market forecasting or a simulated
strategy presented as a validated backtest.


The installed distribution's server, SDK client, symbol preparation, market and
account handlers, and configuration module were compared with the reviewed
revision and matched after normalising checkout line endings. The Windows
Python 3.14 dependency resolution and hashes are retained in
scripts/requirements-windows-py314.lock. Other Python versions need their own
compatible resolution.

EA fix: exact optional magic/symbol/position filters, position identifier, deal
entry/reason/fee metadata and explicit query failure reporting. History uses
integer broker-clock epoch bounds rather than naive datetimes, then filters
normalised UTC instants at millisecond precision. This retains the pinned
upstream broker-clock convention instead of treating every SDK epoch as native UTC.
No broker offset is hardcoded and no order operation is added.

Meu additionally supplies `get_ea_summary` and the local `ea_metrics.py` calculator.
They compute counts, costs and position cohorts with Decimal, validate inputs and
reconcile totals before the model interprets the receipt. No LLM call or new
dependency is used by the calculator. This makes twelve read tools in the Meu adapter;
the upstream execution tools remain absent.

The Meu market-structure helper is original standard-library code. It compares exact
closed-candle high/low sequences and separately confirmed, strict local pivots; it
adds no dependency or prediction service. Existing raw market tools remain compatible.
