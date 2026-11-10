# MT5 market-data adaptation and Windows validation

Date: 2026-11-10. Source branch: `dev/meu-foundation`.
No installer, APK, release or trading capability is published by this change.

## Community source and boundaries

The optional `mt5-market-data` skill adapts
[vincentwongso/mt5-trading-mcp](https://github.com/vincentwongso/mt5-trading-mcp),
reviewed revision `daa905d36135aa1f00017efccc9b39fba7130c3f`, MIT.
The upstream value conversions and other read handlers remain upstream implementations;
the EA follow-up below replaces the positions/history handlers.
Meu supplies a thin launcher that restricts both the MCP registry and SDK surface.
The original licence and source attribution accompany the skill.

The native worker has its own environment: mt5-trading-mcp 1.6.1,
MetaTrader5 5.0.6231, MCP 1.30.0, Windows x64 Python 3.14.
Meu's MCP 2.x environment is unchanged. A hash-locked dependency resolution is
included for the tested worker. Neither core installation nor Android gains this
Windows SDK dependency. The skill is optional in the source tree and explicitly
installed in the owner's existing Windows profile for this trial.

The worker attaches to the explicitly selected `C:\MetaTrader 5\terminal64.exe`.
It verifies terminal identity and the existing connected session. Broker-login
credentials, alternative terminal selection and Market Watch changes are refused.
Order placement, modification, cancellation, closing, screenshots and every
unknown future tool are removed before serving MCP. SDK order/login operations
are additionally blocked. This is a constrained MCP adapter, not a sandbox for
arbitrary Python or the parent agent's terminal tool.

Transport is local stdio, with no HTTP listener or cloud relay. Upstream telemetry
is disabled. Private audit and SQLite paths are explicit. Analysis still uses the
LLM provider selected by the user; relevant tool results can enter that model's
context. No LLM API call was needed for the validation below.

## Initial live checks

- Attached to the chosen already-running terminal, without login or trading changes.
- Meu's MCP 2.x client successfully negotiated with the isolated MCP 1.x worker.
- Listed exactly 11 read tools and called `ping`, `get_symbols`, `get_quote`,
  and `get_rates` against the real terminal.
- XAUUSD returned a positive bid/ask and a UTC tick timestamp approximately one
  second before receipt, at 09:37 UTC on the validation date.
- Retrieved 100 actual H1 candles and validated OHLC bounds. History covered
  2026-11-04 through 2026-11-10, including the current forming candle.
- The installed upstream handler returned chronological candles despite its
  description saying newest first. The adapted skill requires timestamp sorting
  and excludes the forming candle from closed-bar calculations.
- The real Meu host's single-server probe discovered exactly the same 11 tools.
- No account-information, positions or history request was made in the live trial.
  No order request was sent to the broker.

## Safety and source checks

19 offline behavior tests cover tool removal, SDK dispatch refusal, exact terminal
selection, wrong-terminal rejection, credential/telemetry rejection and cleanup.
7 authoring checks and 8 generated-document checks passed (34 total).
All 14 repository lint/health guards also passed on a clean staged source snapshot.
A whole-worktree attempt encountered existing dependency archives in ignored
caches; the clean-source check excludes those local build products without
deleting them.
A separate real MCP-protocol rehearsal used a fake server, rejected five forbidden
RPC names and proved zero mutation-handler executions. Those forbidden calls were
never sent to the live MT5 server.

The local profile configuration was backed up with Windows DPAPI on D: before
adding `meu-mt5-market`. A semantic before/after comparison verified that all
other configuration sections, including model/provider settings, were unchanged.
Market values, logs, audit state, machine-specific configuration and encrypted
backup remain outside the repository.

## Use and remaining scope

In a new Meu chat, ask in ordinary language for XAUUSD/MT5 market data. The skill's
name and description allow normal skill discovery; the user need not supply its
name. New conversations load the connector without changing toolsets in an
already-running conversation. If an old app process has not refreshed its skill
index, restart Meu once after current work finishes.

Example: “Διάβασε το XAUUSD από το MT5 και ανέλυσε τα τελευταία 100 κλεισμένα
κεριά H1. Δείξε ώρα τιμής, spread και τις πηγές. Μόνο ανάγνωση.”
Fetch at least 101 bars when 100 closed bars are required and a forming bar exists.

Positions and history were subsequently live-tested as described below. Other
account endpoints remain read-only and should be used only when relevant to the request. Broker session calendars and chart screenshot
EAs are outside this trial. The upstream market-hours flag is only a trade-mode
heuristic. No strategy performance or profitable-entry claim is established.
Autonomous Android with the PC off cannot read this PC-only MT5 instance; a paired
PC-agent conversation can use the Windows worker while the PC is reachable.
No model-driven desktop chat/UI end-to-end or new GitHub CI run is claimed here.


## EA identity and history interval follow-up

The positions handler now preserves `magic`, stable `identifier` and `reason`.
Both positions and history accept an optional exact numeric magic filter, including
zero. History additionally retains `position_id`, `entry`/`entry_code`, reason,
native type code, fee and normalised UTC milliseconds. A known position can be
queried independently of magic to inspect manual exits. Matching comments alone
is not a sound ownership rule. Shared magic and netting remain attribution limits.

The confirmed time fault was a naive-datetime query interpreted in the Windows
local timezone, while results were converted using upstream's broker-clock offset.
The fix sends integer broker-clock epoch bounds and checks every returned instant
against the requested UTC interval, at millisecond precision. It reads the current
offset inside the SDK call so reconnection can refresh it. No fixed two-hour shift
or global timezone change is introduced. Existing value converters are reused.

An initial diagnostic compared raw SDK epochs with normalised UTC and described
the difference too broadly as a timestamp shift. The selected feed was separately
observed two hours ahead of the system's UTC clock; the pinned worker's broker
normalisation is retained. The corrected independent comparator uses the same
verified clock convention and interval, rather than an unshifted raw SDK interval.
The current inferred offset is not a historical timezone database: intervals
spanning a broker clock/DST change need further verification.

13 new offline contracts cover identity, magic zero, exact symbol/position filters,
entry/exit labels, millisecond boundaries, timezone-aware inputs, zero-offset feeds,
reconnection and failed reads. Together with the existing safety, authoring and
document contracts, 47 tests pass. A real MCP rehearsal on fake data checks the new
input schemas and read-only annotations and still rejects all four mutation tools.

Live candidate checks on the same selected terminal returned EA-filtered positions
and deal history, kept every returned record inside its interval, and matched an
independent direct-SDK query by exact ticket set and identity fields. Private
account records and exact results remain on D: outside the repository. The tool
surface still contains the same eleven read tools; no order or MT5-setting action
was requested. The installed optional worker and profile skill are updated locally.
Finish current Meu work, restart Meu once and start a new conversation to load the
new MCP input schemas without rewriting the cached toolset of an older chat.


## Deterministic EA arithmetic follow-up

The first actual model-only interpretation miscounted deals and costs. Meu now
provides a local `get_ea_summary` read tool, backed by the standard-library
`ea_metrics.py` calculator. It uses bounded, finite Decimal strings with sufficient
precision for all input amounts; no arithmetic is delegated to an LLM. The skill
requires this receipt before interpreting an EA's performance. The raw history
API remains available for inspection, with its existing return shape unchanged.

The receipt groups by position identifier, verifies exact EA/interval scope,
deduplicates identical tickets and rejects conflicting tickets or invalid numbers.
It separates completed, entry-only, exit-only, partial/incomplete and ambiguous
lifecycles. Splitting an exit does not create an extra trade. Reversals and mixed
position directions are not guessed into a completed trade. Non-trade cash records
stay outside trading P/L. Exit-reason names are fixed by SDK codes, including
expert=3, stop_loss=4 and take_profit=5.

History money includes profit, swap, commission and fee. Net amounts by lifecycle
cohort must reconcile exactly with trade-history totals before validation passes.
Floating P/L remains separate, explicitly excluding charges unavailable on an open
position. Both current exposure and its valuation time are stated separately from
the historical interval. Exposure is read before and after history; if its identity,
direction or volume changes during capture, the tool refuses a verified snapshot.

The receipt exposes canonical counts, money, buy/sell cohorts, costs, exact lot
sizes, exit reasons, bounded group details and conservatively available overlap
metrics. It cannot certify strategy quality or prove ownership where several EAs
share a magic/netting position. A model can still misstate prose: the computed
receipt remains the source of truth and the live analysis is checked against it.

Regression fixtures exercise exact fees, partial exits, carry-in and current-open
positions, conflicting/duplicate data, invalid values, exposure changes, ambiguous
reversals/directions, non-trade records and millisecond timing. An MCP protocol
rehearsal also calls the summary with real serialization and proves mutating tools
remain unavailable. No extra base/Android dependency or new distribution is added.

The live MT5 sample for magic 151515 was re-run through the calculator and the same
selected model, with only the summary tool available and no human numeric answers
or corrective turn supplied. Exact receipts, model output and validation evidence
remain in the private D: test workspace. The adapter now has twelve read tools;
the installed allowlist adds only `get_ea_summary`.


## Deterministic market structure follow-up (2026-11-10)

A real XAUUSD interpretation incorrectly labelled `4069.32 -> 4073.37 -> 4073.13`
as rising lows. The optional reader now exposes `get_market_structure`: exact
Decimal comparisons precede narrative interpretation, with chronological evidence,
strict/non-strict/equal/mixed/insufficient verdicts and a separate confirmed-swing
classification. It never turns a mixed candle sequence into a confirmed trend.

Only closed candles enter geometry. Closure is frozen before the SDK read, so a
bar closing during retrieval cannot be promoted from its partial snapshot. Swing
pivots need strict comparisons with closed neighbors on both sides; plateaus and
unconfirmed latest extremes are excluded. Bad OHLC, duplicate/future timestamps,
stale quotes and unsupported calendar-month boundaries refuse verification.

The existing raw quote/rates tools and EA summaries remain compatible. The SDK
mutation allowlist is unchanged; the registry now has thirteen read tools. New
regression tests cover the real failure and the broker-reader wiring. Native MCP
reads of XAUUSD M15/H1/H4 also passed. These are geometry and read-path checks,
not a backtest of prediction accuracy. No release is created by this follow-up.


## Automatic skill and tool selection (2026-11-10)

The MT5 skill's compact catalog description now names MT5, XAUUSD/gold and EA
analysis. Its instructions route market requests to verified structure per
requested timeframe (default M15/H1/H4), EA requests to the exact requested magic
and computed summary (default last seven days), and combined requests to both.
They explicitly forbid substituting unfiltered account history for an EA query.
No core router, dependency or always-preloaded skill body was added.

Three real DeepSeek Flash runs used natural Greek requests for XAUUSD, EA 151515
and both. The regular skill catalog and tool-search bridge were enabled alongside
other public repository skills. No prompt named a skill/tool, supplied its body,
forced tool choice, or contained corrected metrics. In each run, the model loaded
the MT5 skill itself before broker reads; market requests used all three structure
timeframes, EA requests used magic 151515 and a seven-day summary, and the combined
request used both. One combined run additionally read positions with that exact
magic. No account-wide history or trading operation was used.

This validates autonomous selection and scoping, not every narrative claim. The
EA-only response still made unsupported directional/payoff generalisations from
a small sample. That separate interpretation-quality finding is retained for
follow-up; it must not be represented as a passed strategy analysis or forecast.


## Evidence-bounded EA narrative follow-up (2026-11-10)

Automatic tool selection exposed a separate interpretation defect: the model
inferred all buy positions won from positive buy net, inverted a payoff comparison,
and inferred an EA mechanism from lots/overlap/hold time. The receipt now supplies
net-based wins/losses/breakeven counts and outcome mix for each direction, winning
and losing-position means, mean net, and both explicitly named payoff ratios.
Undefined denominators remain null; tiny nonzero values do not round to zero.
Exact accounting totals and the existing fields remain compatible.

The reader also returns `descriptive_report` and `bounded_conclusions`, built
from the computed receipt by code. The skill uses the report for a concise
evidence table and restricts prose conclusions to the code-built bounded
predicates, preserving their sample scope and outcome counts. It forbids additional uncomputed percentages,
unsupported all/always claims, silent interval expansion, conflating expert exits
with SL, and strategy/future-return conclusions from a bounded observation.
A positive SL result is not proof of stop movement. Floating P/L remains separate.

Tests use synthetic mixed-direction outcomes, one-sided/zero samples, net-after-
cost classification, payoff denominators, boundary/partial exclusions and tiny
values. Real-provider checks must additionally exercise natural-language analysis
and false-premise questions without preloading the skill or supplying corrections.
These checks validate the observed responses, not a guarantee about arbitrary
future model prose or predictive performance. No distribution is created here.
