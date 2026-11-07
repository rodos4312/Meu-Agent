# Coordinator progress and review receipts — 2026-11-07

Source-only follow-up on `dev/meu-foundation`. No installer, APK, tag, version
bump, update-feed promotion or installed-app change belongs to this batch.

## Verified baseline

The preceding deliverables commit `014a0e086e46fbdd6ace5cac6e97597b4e538171`
passed all six required jobs in [GitHub run 42378874081](https://github.com/rodos4312/Meu-Agent/actions/runs/42378874081).
Release/publication jobs were intentionally skipped. That receipt does not
certify the later Coordinator commit; its own CI result must be checked.

## Changes

- The native Coordinator now exposes a bounded, redacted display projection
  shared by its tool result and the profile-owned project workspace. The
  checkpoint format and execution authority remain unchanged.
- Windows chat and project workspace share task presentation: acceptance
  criteria, dependencies, actual attempt/model, repair check, expandable
  recorded evidence and verified deliverables. Progress counts native
  `verified` states only. Unknown state is never interpreted as pending or pass.
- An independent review reports its concrete check, observation and verdict
  only when its schema and reviewed task attempt/artifact hashes match the
  checkpoint. A reported pass remains awaiting verification until accepted by
  the parent. Changed reviewed attempts hide obsolete review findings.
- Retrying/running/interrupted tasks hide the previous helper's model and
  evidence. Windows can display the current helper model only through an exact
  native dispatch identity in that chat's scoped roster.
- A real Windows rehearsal found and fixed a missing history path: a single
  deferred `tool_call` containing `coordinate_project` now restores the same
  progress card after reload. Ambiguous mixed batches are not guessed into a
  project card. Generic failed/stopped-call presentation remains available.
- Android displays the same saved native task/review receipt in its existing
  chat. Accepted tool completions attach a small message-owned projection;
  saved named results and exact call-bound bridge steps restore it. Prose and
  user JSON cannot create progress. Same-turn reconnect carries the existing
  projection; no new runtime, provider selection or polling loop is added.
- Nine UI locales per client include the new labels. No approval defaults,
  provider boundaries, concurrency limits or automatic retry policy changed.

## Local evidence

- **104 distinct Python tests passed** across Coordinator routing/plans,
  background dispatch, review/repair, interrupted-project rehearsal, memory,
  Auto routing, project RPC isolation and generated-contract consistency. The first combined run exposed an
  old exact-shape RPC expectation; after updating that assertion for additive
  fields, all 27 RPC tests passed. Tests use `scripts/run_tests.sh` with the
  isolated interpreter and temporary product homes.
- **42 Windows UI tests passed in seven suites**, including the new receipt
  projection/component tests, existing stopped-tool/card behavior, workspace,
  model preferences and translation coverage. Typechecking, scoped ESLint and
  renderer/Electron source build passed.
- **Two real Electron scenarios passed**: a real native Coordinator status
  result reached the renderer via a deterministic mock-provider tool call and
  restored its acceptance/review card after reload; the selected Coordinator
  also survived closing and reopening the temporary desktop application.
  The review/checkpoint in this UI rehearsal is a synthetic fixture, not a
  claim of a fresh live-provider project acceptance.
- **114 Flutter tests passed in four suites**, covering the new projection,
  canonical bridge-history restoration, runtime ownership, existing subagent
  events, session reconciliation and deliverables. The five projection/layout
  tests were rerun after final typography changes. Changed code/tests passed
  Flutter analysis without findings. Phone-width light/dark renders were
  inspected at 390×844.

Local screenshots are retained in `Meu-experience-evidence-2026-11-07` beside
the checkout. Complete Android 9673 source and per-file checksums are preserved
in the private source archive; this is not an APK.

## Acceptance limits

These cards show saved native progress, not a new independent execution
engine or an assertion that files remain unchanged forever. Existing live
helper views and parent verification own execution and acceptance. No new
external-provider request or paid-model call was needed for this batch.

Physical Android background/reopen acceptance, mobile-data transitions,
on-device runtime/provider combinations and real Windows reboot recovery
remain final-candidate checks. No new distribution is published here.
