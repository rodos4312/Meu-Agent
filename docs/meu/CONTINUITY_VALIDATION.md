# Conversation continuity — 2026-11-07

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
