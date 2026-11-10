---
title: "Mt5 Market Data — Analyze MT5/XAUUSD, gold and EA trades read-only"
sidebar_label: "Mt5 Market Data"
description: "Analyze MT5/XAUUSD, gold and EA trades read-only"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Mt5 Market Data

Analyze MT5/XAUUSD, gold and EA trades read-only.

## Skill metadata

| | |
|---|---|
| Source | Optional — install with `hermes skills install official/research/mt5-market-data` |
| Path | `optional-skills/research/mt5-market-data` |
| Version | `1.0.0-meu.6` |
| Author | rodos4312 (Meu), adapted from Vincent Wongso Saputro and mt5-mcp contributors |
| License | MIT |
| Platforms | windows, linux, macos |
| Tags | `MT5`, `MetaTrader`, `Market`, `Forex`, `XAUUSD`, `Broker`, `Candles`, `Positions` |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# MT5 Market Data Skill

Read real broker data through the configured Meu data-only MT5 MCP connection.
Use this skill automatically for MT5 prices, gold/forex analysis, candles,
spread, positions, orders and history; the user need not name the skill.

## When to Use

- Questions such as "τι κάνει ο χρυσός", "δείξε EURUSD", "δες τις θέσεις μου",
  "έχει τάση ή συσσώρευση", or requests for MT5 market/account observations.
- Natural requests such as "δες XAUUSD", "τι κάνει ο χρυσός", "ανάλυσε το EA 151515",
  "des xauusd" or "des to ea 151515" require automatic skill selection. The number is
  the requested EA magic, not a hardcoded account, ticket or skill name.
- Diagnose differences between a displayed MT5 chart, a quote and account state.
- Obtain exact broker candles before discussing price action or computing indicators.

## Prerequisites

- A configured `meu-mt5-market` MCP server exposing the read tools below.
- The Windows worker attaches to one explicit terminal already logged in by its owner.
  Analysis may be requested from any Meu client connected to that worker.
- Autonomous Android cannot run the Windows MT5 SDK. It needs a configured remote
  connection to the PC's Meu/MT5 worker to obtain that PC's broker data.
- Setup and the optional isolated worker are documented in `references/setup.md`.
  Neither analysis nor this skill requires a second model provider or news API key.

## How to Run

Use `tool_search` to discover the configured server's names, which may be prefixed.
Call the MCP tools directly. Do not replace broker data with public quotes or shell
scraping. If the connector is absent, explain the setup dependency instead of
inventing a quote.

Choose the read path from the request after loading this skill:

- Market/price/trend request -> `get_market_structure` for the requested timeframes;
  if unspecified, use M15, H1 and H4 and state that choice. Use the exact broker symbol.
- EA/performance request -> `get_ea_summary` with the explicitly requested numeric
  magic. Without an interval, use the last seven days ending at the runtime's current
  time and state the interval/timezone. Never interpret the magic as a ticket/login.
- A request mentioning both needs BOTH paths. Keep market geometry and EA results
  separate; do not claim historical market/EA causality from a current snapshot.
- Never substitute an unfiltered account-wide history/positions read for an EA request.
  Missing magic is a genuine missing choice; a supplied magic needs no reconfirmation.
- If the verified tool is unavailable, report that dependency. Do not silently compute
  an equivalent in prose, use unrelated public quotes, or ask the user to name a skill.

| Tool | Use |
| --- | --- |
| `get_market_structure(symbol, timeframe, count=120)` | Exact closed-candle high/low comparisons and separately confirmed swing structure. Use first before market trend labels. |
| `get_ea_summary(from_ts, to_ts, magic, symbol=None)` | Verified Decimal counts, full/incomplete positions, costs, realised history and separate floating P/L. Use first for EA analysis. |
| `ping` | Verify connectivity after idle periods or errors. |
| `get_terminal_info` | Confirm the selected terminal and broker connection. |
| `get_account_info` | Balance, equity, margin, currency and leverage. |
| `get_quote(symbol)` | Exact broker bid/ask and last-tick timestamp. |
| `get_symbols(category=None)` | Discover broker names, suffixes and specifications. |
| `get_rates(symbol, timeframe, count)` | Actual OHLCV candles, including the forming bar; sort by timestamp. |
| `get_market_hours(symbol)` | Broker trade-mode observation; not a verified session calendar. |
| `calc_margin(symbol, side, volume, price=None)` | Broker calculation for a hypothetical order; does not place it. |
| `get_positions(symbol=None, magic=None)` | Positions, P/L, magic, identifier and reason. |
| `get_orders(symbol=None)` | Existing pending orders. |
| `get_history(from_ts, to_ts, symbol=None, magic=None, position_id=None)` | Entry/exit deals in a timezone-aware interval; exact filters combine with AND. |

## Quick Reference

- Broker symbols are exact: retain suffixes such as EURUSD.a or XAUUSDm.
  Use `get_symbols` when a name is ambiguous. Do not map gold to a futures proxy.
- Timeframes: M1, M5, M15, M30, H1, H4, D1, W1, MN1.
- Prices and amounts are decimal strings. Use Decimal arithmetic for money.
- History times require timezone-aware ISO 8601 values, preferably UTC.
- An empty successful positions/history list is valid. An SDK failure is an error, not an empty account.
- Use numeric `magic` to select an EA; `magic=0` is a real filter for unassigned/manual records.
  Comments can change on exits and do not reliably identify an EA.
- History retains `position_id`, `entry`, `entry_code`, `reason`, `fee` and UTC `time_msc`.
  Entry/exit deal counts are not counts of completed trades.
- For a complete position lifecycle, use its `identifier` as `position_id` without a magic
  filter; this also finds a manual exit whose magic differs. Shared magic or netting
  positions may make attribution ambiguous; say so instead of assigning ownership.
- This reader does not enable invisible symbols in Market Watch automatically.
  Ask the owner to enable the exact symbol there if needed.

## Procedure

1. For any EA performance analysis, call `get_ea_summary` with the exact magic and
   explicit interval BEFORE writing numeric observations. Its `validation.status` must
   be `passed` and reconciliation difference zero. Quote its calculated fields; do not
   count raw history or calculate totals in prose. If it fails, report the actual error.
   For EA conclusions, use `descriptive_report` as the factual backbone. Render a
   concise evidence table. For any prose conclusions, ONLY quote/translate or
   shorten `bounded_conclusions` without changing their predicates or scope. Do
   not add your own attribution ("entirely due to one trade"), arithmetic, extra
   percentages, numerical comparisons or causal/strategy explanations from the
   raw groups. Do not infer losing SL outcomes from exit-reason counts.
   Finish with the sample limitation; omit all other editorial conclusions.
   Keep one requested/default interval; do not silently expand it or call a bounded
   query "all available history". Then use this bounded evidence-first format:
   - State complete-position count and interval; for EACH direction give count,
     wins, losses, breakeven and net from `complete_trades.by_direction`.
   - Positive net is not "all wins". Say "all" only when that direction's
     `outcome_mix` is `all_wins`/`all_losses`, and always qualify "in this sample".
   - Quote the supplied average fields and ratios with their meaning. Do not
     invert them, calculate new payoff/break-even ratios in prose or treat a
     descriptive amount ratio as a forecast of required future winning trades.
   - Copy exit-reason counts faithfully: an expert exit is not a stop loss. A positive
     SL result alone does not prove that a stop was moved or reveal its placement.
   - Describe observations in this interval, not "systematically", "always" or
     claims of future profitability. Lots, hold time and lack of observed overlap
     do not identify grid/martingale, scalp/swing rules or stop distance.
   - Keep floating P/L separate; do not assume closure price/fees or predict the
     final weekly net. If a conclusion lacks computed evidence, omit it. Explain
     what extra evidence is needed if the user specifically asks for that claim.
2. Check `ping`; use `get_terminal_info` when diagnosing the connection. Never
   switch terminal or broker account implicitly.
3. Before any market trend/high-low claim, call `get_market_structure` for EACH requested
   timeframe. Require `validation.status=passed`. Use its comparisons and classification,
   not a visually selected subsequence. `mixed`, `flat`, non-strict equality or `insufficient`
   must not be described as strictly rising/falling highs/lows. Quote the exact sample times.
   Distinguish `recent_candle_structure` from `confirmed_swing_structure`; neither alone
   proves a general trend, a profitable strategy or a forecast probability.
4. Retrieve the exact symbol metadata and `get_quote`. State the broker, timeframe,
   quote timestamp, bid/ask and spread when relevant.
5. Fetch a bounded history, normally 100-300 bars, for price-action questions.
   Exclude the forming candle for closed-bar indicators and state the method used.
   Sort chronological before calculations. Treat tick volume as tick volume,
   not exchange volume.
6. Separate observations from scenarios. A range, RSI extreme or moving-average
   relationship is not proof of a profitable entry. Do not present a rule-based
   observation as a tested strategy or a Strategy Tester result.
7. Use Meu's currently selected model for explanation. The tools do not call a
   separate narrative service. Match the user's language.
8. For EA history, specify an explicit interval and magic. All returned records must lie
   inside that UTC interval. State the timezone when displaying local times.
9. Include tool results and file links when creating a report. Store reports only
   in the user's selected project/output location; avoid publishing account details.

## Pitfalls

- Check the last-tick age before saying a price is current. Closed markets, old
  history and disconnected feeds can return plausible but stale values.
- Upstream `get_market_hours` derives `is_open` from trade mode; its next-open and
  next-close fields are unknown. Check the broker's actual schedule when needed.
- There is no order-placement, modification, cancellation or position-closing
  tool in this connection. Do not attempt to work around this through `terminal`.
- Chart screenshots require a separate MQL5 EA upstream. This initial reader
  deliberately omits that tool; do not install or attach an EA as a read operation.
- The pinned worker derives a current broker-clock offset. Long history spanning a broker
  clock/DST change needs additional verification; a current offset is not a historical timezone database.
- Distinguish "not enough history" from a model failure. Explain the actual error
  and avoid blind retry loops.
- Read only account information necessary for the request; omit account identifiers
  from logs, public reports and examples.

## Verification

- The connection reports only its thirteen read tools, including computed EA and market-structure summaries.
- Market geometry uses Decimal inequalities on closed candles; equal prices never count as strict higher/lower.
- A pivot needs strict comparisons with closed neighbors on BOTH sides. Plateaus and unconfirmed latest extremes
  do not become pivots. Mixed or insufficient structures remain explicit.
- Market reads use a fresh quote and a closure cutoff frozen before fetching candles, so a candle closing
  during the read cannot be promoted from a partial snapshot. MN1 calendar boundaries are unsupported
  by this fixed-duration structure helper; use raw data without claiming a verified structure.
- Summary money uses exact Decimal arithmetic and includes profit, swap, commission and fee.
- Compare `history_totals.net`, `complete_trades.net` and `net_by_status`: these describe
  different cohorts. Floating P/L is separate and excludes charges unavailable on open positions.
- Identical duplicate tickets are ignored once; conflicting data refuses verification.
- Reversals, mixed directions, partial/incomplete history and changed exposure are not guessed
  into completed trades. Exit reasons describe exit deals of complete in-window lifecycles.
- A reason code of 3 means EA/script, 4 means SL and 5 means TP; a positive SL exit is possible.
- The model interprets a computed receipt; that receipt does not validate strategy quality.
- The worker confirms the configured terminal installation before serving data.
- Mutating SDK operations and broker-login overrides are refused by the adapter.
- A successful ping alone is not a price test: verify a quote and actual candles.
- Preserve exact source and timestamps; do not claim live testing from mocked data.

## Attribution

Adapted from the community `mt5-market-data` skill in
vincentwongso/mt5-trading-mcp, revision daa905d36135aa1f00017efccc9b39fba7130c3f.
See `references/provenance.md` and `LICENSE.upstream` for source and licence.
