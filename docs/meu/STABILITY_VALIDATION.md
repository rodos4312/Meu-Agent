# Consolidated stability checks — 2026-11-07

Source changes stay on `dev/meu-foundation`. No release, installer/APK, version
bump, update-feed promotion or installed-app change belongs to this batch.
The recovered Android source remains build 9673.

## Previous GitHub gate

All six required jobs for continuity commit `cdf32d00cd25` completed successfully
in [run 42386571625](https://github.com/rodos4312/Meu-Agent/actions/runs/42386571625):
Windows pinned backend upgrade, privacy/memory/DeepSeek, installer/CI routing,
identity/isolation, isolated navigation/continuity, and Linux Coordinator.
The three optional release/publication/rollback jobs were deliberately skipped.
This result applies to that exact commit, not automatically to subsequent edits.

## Reproduced Windows startup faults

Readiness previously checked cancellation only between probes. An in-flight
health or legacy status request could keep the old startup pending and return
success after its settings had been superseded. Completed retry delays also
retained abort listeners: twelve transient failures left twelve listeners.

Both probe routes and retry waits now use the existing cancellable startup
step. Retiring the attempt rejects immediately; a later network result cannot
make it ready. Node's cancellable timer releases its listener on completion.
This does not stop the canonical gateway, start another owner, change provider
or turn transient failures into authentication rejections.

The three added cases failed before the fix and pass afterward. Existing
401/403, retryable 429/5xx, legacy-route and bounded-timeout tests still pass.

## Reproduced Android stop/start race

The runtime screen accepted a late `ready` result after explicit stop and
requested credentials again. A late `error` similarly overwrote the stopped
state with an obsolete failure. Both cases failed before the fix.

Each startup/login continuation now belongs to one screen attempt. Confirmed
stop and disposal retire that attempt; stale status, credentials, login and
connection-store continuations cannot advance it. Notification opt-in, stop
confirmation, stored keys and saved conversation identifiers are retained.

Three existing source-contract assertions assumed LF line endings. Their
reader now normalizes CRLF; production manifest/background behavior was not
changed to satisfy those text assertions.

## Local automated evidence

- Windows: **115 tests in 10 Electron suites** passed: startup, cancellation,
  readiness, ownership, reauthentication and update recovery. The final
  formatted readiness suite passed again (**21 tests**).
- Python: **67 tests in 8 isolated files** passed via `scripts/run_tests.sh`:
  no Nous usage telemetry, provider-locked Auto routing, installer privacy,
  update recovery, mobile pairing/relay and profile-scoped pairing stores.
  These are behavioral contracts, not a whole-machine packet capture or
  certification of every optional third-party plugin.
- Android: **725 tests in 22 suites** passed together with flavor `meu` and
  `MEU_PROOT_EXPERIMENT=true`: cold-start owner selection, session resume,
  outbox/drafts, cancellation, background demand, auth rejection, snapshot
  privacy, Coordinator and delivered files. All three edited Dart files passed
  analysis; the four runtime widget tests passed again afterward.
- **Two real Electron/canonical-backend rehearsals** passed: socket loss and
  closing/reopening the app. The conversation route, unsent draft and final
  answer survive; the database and mock provider each prove one admitted user
  message. This uses an isolated test home and deterministic model, not a paid
  provider or the installed Meu.
- Windows ESLint, TypeScript checks and production build passed. The local
  working-tree build is a test artifact, not a published release.

## Remaining acceptance before grouped distribution

Automated tests do not certify Android process death, screen lock, OEM battery
restrictions, mobile-data reconnect, native PRoot execution or phone file
export. Those need a real phone with the final candidate. Actual Windows
reboot and the final installer/update rehearsal likewise remain separate.
Keep these pending rather than labeling milestone 5 or the distribution ready.

No extra routine approval prompts, provider switching defaults or memory/skill
permissions were introduced.
