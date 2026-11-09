# Conversation continuity — 2026-11-07

## Offline profile sync repair — 2026-11-09

The owner reported divergent histories while the Windows app was updating and
the autonomous Android agent continued working. The exact phone transcript has
not been inspected or altered. Two independently reproduced defects allowed a
live partial answer to be exported and classified a running destination as a
conflict before checking its write guard. Export now uses one read-only SQLite
snapshot and defers live, queued or uncertain work; import checks the running
writer before comparing history. Android distinguishes an explicit busy receipt
from a real divergent transcript and retries through its existing sync loop.

A real divergence now has an explicit recovery protocol. Both compared copies
are saved in the owning database before the standard soft-archive rewind keeps
the selected continuation under the same session ID. Per-device expected
fingerprints refuse newer messages; a durable shared receipt handles retries
after a lost response without overwriting later work. A phone-side refusal after
the PC commit leaves its newer history intact and both compared versions in the
PC backup. There is no distributed all-or-nothing claim. No agent turn, tool
call, model/provider configuration or project-file operation is admitted by this
endpoint. Personal-space authorization applies to recovery and backup reads.

Android shows only the differing suffixes after the common prefix and offers
continuation from phone or PC. Neither is automatically selected for a genuine
conflict. Saved text copies remain readable from the phone's database with the
PC off; full displaced local message/tool rows are soft-archived, not deleted.
Recovery stamps a durable revision: warm agents reload the selected history
before answering, including equal-length or shorter continuations. Both the
desktop/TUI path and messaging cache honor this revision. Ordinary appends
retain the existing prompt cache behavior. The Android candidate must include
the same reviewed engine revision; a helper-only update is insufficient.
The shared helper is pinned by its source commit and hash. The full-runtime default
and existing package, signer, data paths and saved pairing remain unchanged.

Validation: 63 backend cases passed across sync, recovery, quiescence, private
TLS transport, named spaces and listener restart. All 18 Android recovery/sync and
full-flavor navigation tests passed, with targeted analysis clear. Two real
Python bridge checks passed against both the current core and the precise
Android engine revision `6fd190781a67d20130c4febcc3c03715b5e9eefe` on Windows.
The additional warm-history checks cover stamped/unstamped live transcripts,
shorter/equal/longer recovery and gateway re-baselining. A Windows-only test
harness defect was corrected so subprocess pipe readers retain real threads.
Two further regressions were reproduced when a chosen history ended with an
unanswered user row. Recovery now cuts at the next prompt's physical row before
alternation repair, preventing that prompt from merging into or duplicating
the recovered history. Both stamped and unstamped warm sessions are covered.
These host checks are not physical Android/PRoot acceptance. Candidate builds,
GitHub checks and the owner's already-conflicted conversation still require
their own verification; no installed app or live transcript was changed here.

Source work stays on `dev/meu-foundation`. This batch does not publish an
installer, APK, release tag or update-feed change, and does not modify the
installed applications.

## Reproduced defects and changes

### Windows reconnect belongs to the selected owner

The reconnect controller previously kept one global in-flight promise. After
the selected gateway route changed, a manual reconnect reused the previous
route's pending operation. A late completion could also clear the newer
operation's guard. A stale registration disposer could remove a later
registration of the same handler.

The controller now binds each operation to its exact registration and the
existing gateway activation epoch. Repeated clicks for that same owner still
coalesce. Selecting another owner starts its own recovery; a queued callback
from the old selection is rejected before dialing. Old completion/cleanup
cannot clear the current operation. The boot hook supplies its canonical
activation epoch, without a second connection manager or runtime.

### Android reopens the selected PC instead of forcing local setup

The PRoot preview previously initialized `_showOnboarding` to true on every
launch, even with completed onboarding and a selected remote PC connection.
That forced the local runtime preparation screen into the cold-start path.
Three existing app-level cold-start tests reproduced the problem under the
actual Meu preview defines.

A small launch policy now distinguishes a fresh installation, the selected
autonomous phone runtime and an existing PC connection. The selected phone
runtime still prepares on launch. A configured PC returns through the existing
encrypted route/cache/draft and authoritative resume machinery. An ambiguous
set of saved connections does not silently choose a local runtime. No
credentials, session IDs, approval defaults or pairing protocols are migrated.

## Validation

- **66 Windows UI tests in ten suites passed**, covering reconnect ownership,
  old/new-operation ordering, bounded resume retries, warm replay barriers,
  route commits, reload targets and persistent draft scopes. New regressions
  were observed against the original reconnect controller before the fix.
- **379 Flutter tests in thirteen suites passed** with the Meu flavor and
  `MEU_PROOT_EXPERIMENT=true`. Coverage includes real loopback protocol
  admission fixtures, resume/cold-start, encrypted draft/outbox persistence,
  uncertain-send FIFO blocking, profile isolation, stale response guards,
  runtime launch, Coordinator receipts, deliverables and bidirectional
  transcript reconciliation. The original three cold-start failures pass
  after the launch-policy correction, without weakening their assertions.
- Changed Android code/tests passed static analysis without findings. Windows
  scoped ESLint, TypeScript/Electron/E2E typechecking and source build passed.
- Two real Electron scenarios use the real gateway and temporary product
  homes with a deterministic mock model: disconnect the socket carrying the
  actual prompt, or close the application while its answer is held. After
  reconnect/reopen, assert the same stored route, the full answer, the unsent
  follow-up and no stale running spinner. A read-only SQLite query verifies
  exactly one durable user row, independently of the UI; the mock model sees
  the prompt exactly once. Reconnect creates a fresh viewer connection, not
  another execution owner.

The Windows CI includes the new reconnect/draft suites and the continuity
Electron rehearsal. A local receipt is not a claim that a later GitHub run
has completed; consult the exact commit's run.

## Scope and remaining device acceptance

The existing canonical gateway owns PC work after the desktop viewer closes.
The phone's autonomous runtime remains a separate execution owner. Shared
history does not move tools, processes or project files between devices.
Uncertain sends retain their identity and require reconciliation; recovery
does not automatically send the command again under a fresh identity.

Physical Android process death, screen-lock/background endurance, Wi-Fi to
mobile-data transitions and native PRoot startup remain final-candidate
acceptance checks. A PC shutdown or owner-process crash is different from
closing its viewer: interrupted work is reconciled, not described as still
running. No additional network-access service or relay is introduced here.
