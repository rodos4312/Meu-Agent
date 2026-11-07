# Ordered Coordinator review validation — 2026-11-07

Source-only changes on `dev/meu-foundation`. No distribution, APK, installer
promotion, application version, release tag, update feed or installed app is
changed. Both existing Coordinator variants use the shared pipeline.

## Behavior

New project plans automatically expand standard/complex writing deliverables
into implementation → requirements review → quality review. The parent verifies
each exact attempt; downstream tasks require the quality pass as well as the
implementation. The review goal, original acceptance criteria and check/observed
receipt appear through the existing progress-card task projection on both
clients. No new client polling or execution engine is introduced.

Routine mechanical and read-only tasks retain their existing call counts.
`review_policy: two_stage` supports an explicit strict SDD trial in the same
engine, including for a small task. No third backend or new approval defaults
are needed. Old checkpoints retain their saved task graph and behavior.

Repairs invalidate both staged reviews. Reaccepting changed file hashes at the
same implementation attempt cannot reuse a previous review. Quality receipts
also record the accepted requirements attempt. Per-task three-attempt budgets
survive repairs. Unrelated verified tasks remain accepted.

## Local checks

- The first regression run on the previous implementation reproduced five
  failures for missing gates/policy validation; two lightweight cases passed.
- **75 distinct tests passed across eight Coordinator suites**, through `scripts/run_tests.sh`
  on native Windows, with two workers, no retries and normal time limits.
  This includes 14 staged-review cases, routing/provider isolation, persisted
  projects, review repair, background execution, project memory and progress.
- The real-file/process-death rehearsal now continues into both new reviewers
  after repairing the interrupted report. Each reviewer reads the actual JSON
  through native file tools; its attempted write is refused and the file is
  unchanged. All mock-provider requests target `api.deepseek.com`; external
  sockets are refused. The report and complete graph are accepted only after
  the two ordered passes. These are deterministic model fixtures, not a
  measurement of real LLM judgment quality.
- **101 additional integration tests passed** for delegation backends, profile
  routing, fixed child models, route fields, web settings, project RPCs and CI
  dispatch. One existing POSIX-only hosted-plugin test was skipped on Windows;
  its Linux lane remains required. The 14 staged cases were rerun with this
  integration batch and are counted only once above.
- **Seven SDD authoring checks passed**, filtered to the updated optional skill.
  Workflow YAML parsing confirms the new suite reaches both required lanes.
- **All 14 repository quality checks passed** against the staged source:
  `scripts/check --base HEAD --staged`, with zero blocking or advisory
  code-health findings. Scoped Ruff and whitespace checks also passed.

The new suite is included in both existing Linux and Windows validation lanes.
[Run 42404314243](https://github.com/rodos4312/Meu-Agent/actions/runs/42404314243)
on implementation commit `0fa3437fc536` passed five required jobs, including the
Linux Coordinator and Windows privacy/Coordinator suites. Its Windows UI lane
failed because the old rehearsal expected `1/2 verified` after the new planner
correctly added two reviewers and returned `1/4 verified`.

The UI rehearsal now seeds the actual generated requirements/quality pair:
implementation and requirements are accepted; quality reports a pass but still
awaits acceptance. It requires `2/3 verified`, both stage names and the review
receipt before and after reload. Both real Electron scenarios passed locally
(72 seconds), with an isolated backend and mock provider. E2E TypeScript and
Prettier checks passed. No production behavior or runtime gates were weakened.
## Follow-up GitHub receipt

[Run 42407732228](https://github.com/rodos4312/Meu-Agent/actions/runs/42407732228)
completed successfully for exact source commit
`1d0f725dca188ac72abb41f2ef9cdcd7bfb5c0af`, on `dev/meu-foundation`.
All six required jobs passed; the three optional distribution jobs were
skipped. No release or update-feed promotion was requested.

- The native Electron navigation lane passed all **10 scenarios**, including
  the corrected staged-review card/reload and Coordinator close/reopen cases.
- Linux passed the staged suite (**14 cases**), the previously Windows-skipped
  hosted-plugin case, and its broader integration batch (**206 passed, one
  skipped**). These counts overlap; they are not added as distinct new tests.
- The Windows privacy lane reported **1,648 passed, 17 skipped** in its main
  batch, followed by **395 passed, 11 skipped**, **18 passed**, and **50 passed**
  in its additional batches. The main batch retried one file: see below.
- Windows identity/isolation, validation-only packaging, installer smoke test
  and the full native CI replay passed. Replay reported **101 passed, one
  existing POSIX-only skip** with normal file budgets.
- The follow-up's local scoped health/Ruff checks passed, with zero blocking
  or advisory findings. The two local Electron scenarios remain separate
  evidence from the hosted lane.

### Known intermittent cancellation-suite failure

`tests/tools/test_delegate_capacity_interrupt.py` failed three first-attempt
cases (soft stop with submission failure, partial submission failure and a
stop during capacity admission). The output includes missed five-second event
waits, a worker still alive during cleanup and a mismatched completion ID in
a later case. All 13 cases passed in the fresh automatic retry. The cause is
not established by this receipt; do not call it fixed or silently hide the
first failure. Investigate synchronization and cleanup before claiming a
flake-free stability result. No retries, assertions or timeouts were weakened.

Final distribution and physical-device acceptance remain pending.

## Scope and limitations

Both Windows and Android have source changes for navigation, deliverables,
previews, Coordinator visibility and conversation continuity. Paired Android
uses the PC backend's Coordinator. Autonomous Android uses its packaged engine;
the current mobile seed/guest pin is still `cb43517b6dbd`. Regenerate that seed
and the matching installer hashes from the admitted engine revision before
building the consolidated APK. Source UI checks do not prove that an installed
phone already runs the ordered review gates. Physical-device acceptance remains
separate for paired and autonomous modes.

This is runtime gating for `coordinate_project`, not an OS sandbox or proof
that an LLM actually performed a claimed check. The parent still runs relevant
checks and records evidence. Ordinary direct delegation remains available;
provider instructions send consequential implementation into project plans.
Workload classification is semantic and can be wrong. Read-only research needs
an explicit strict policy when a two-stage review is desired.

The optional SDD skill's Meu adapter describes this contract and suitable TDD,
bounded revision, interruption and evidence handling without blanket commits
or extra user prompts.

## Community sources inspected

- [Native SDD workflow](https://hermes-agent.nousresearch.com/docs/user-guide/skills/optional/software-development/software-development-subagent-driven-development):
  implementation, requirements review, then quality review. Meu already ships
  this optional skill; the new adapter maps it to saved native project gates.
- [magnus919/hermes-council at e360453](https://github.com/magnus919/hermes-council/tree/e360453b2326225fffad289bda9b438aca5df995):
  the current README describes a plugin foundation without council execution;
  it is not an executable SKILL-only debate in this revision.
- [Ridwannurudeen/hermes-council at aefd0c](https://github.com/Ridwannurudeen/hermes-council/tree/aefd0cfa131c1cf632b1efcd0fc4e231a8f7932b):
  an actual MCP implementation with persona deliberation and an arbiter.
  Its inspected `client.py` resolves a separate environment-based provider
  client, including OpenRouter/Nous/OpenAI choices, rather than inheriting the
  active Meu session. Ideas retained: explicit checks, missing evidence and
  unresolved disagreement. No package, external client or code was imported.

Both community repositories were inspected statically, not installed or run.
