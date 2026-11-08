# Consolidated preview 26 — frozen scope

Preparation date: 2026-11-08. Windows candidate `0.1.0-dev.26`; Android input
source advances from 9673 to candidate 9674. Development branch only. No further
feature additions belong in this candidate. A draft/candidate is not a public
release or an update-feed promotion.

This consolidates the previously recorded navigation, deliverables, Coordinator,
continuity, provider and runtime work. The final additions are only:

- Correct the bootstrap pin test's cold Windows PowerShell subprocess budget
  from 30 to 60 seconds, consistent with its other native bootstrap checks.
  Its hash/source authority assertions are unchanged. This is not a change to
  the installed updater's timeout. The final Windows privacy lane disables
  file retries so an intermittent failure cannot be hidden by a green retry.
- Add PC–phone file transfers over the existing authenticated connection or
  saved certificate-pinned pairing. No additional account, key or listener.

## File transfer behavior

In Windows, choose a folder in Settings → Gateways → This window → PC–phone
file transfers. The grant is persisted in that owning profile's existing
database, with a fresh identity whenever the selection changes. Stop sharing
revokes it. A phone cannot choose or expand the PC folder.

In Android, open PC file transfers from the main menu. The saved PC pairing is
used when available; otherwise the selected connected-PC route and profile
supply their existing authentication. The screen names its destination. It
does not silently fall back from an offline paired PC to local-phone storage.

The first version lists regular files directly in the selected folder, up to
1,000 entries, and transfers up to 256 MiB per file. Upload/download progress
reports actual bytes. Uploads stage privately, enforce the streaming byte cap
and publish exclusively: a same-name file is never overwritten, including a
collision after admission. Cancellation/disconnection removes partial staging;
an admitted disk write drains before its handle is closed. An uncertain upload
is not automatically replayed. Refresh shows the actual resulting files.

Downloads use bounded disk streaming. Android's own document picker chooses
where to save the completed cache file, without buffering it all in Dart.
Cancelling the save picker leaves the original PC file intact. Both directions
require the PC to be online. This is not background folder synchronization or
an automatic transfer of project execution between computers.

## Source validation

Candidate preparation follow-up: core source `245a2db849bf` passed the Windows
privacy lane with zero file retries: 1,801 cases in its first batch (31 skips),
395 in the recovery/catalog batch (11 skips), then 18 usage and 50 attribution/
connector cases. All seven native PowerShell bootstrap cases passed on their
first attempt. Windows navigation, pinned backend upgrade, Linux coordinator
and real Windows phone-pairing jobs also passed. The Windows identity job
exposed an incomplete connection-form test bridge after mounting the transfer
panel; its focused module is now isolated there, while its own native-bridge
tests remain mandatory. The exact failed four-file group subsequently passed
all 82 cases locally; the combined transfer/pairing/connection group passed 48.
Final candidate CI must still pass; the earlier run is not an all-green receipt.

Android's five final transfer/navigation/streaming suites passed 32 cases.
The private Meu debug APK was assembled and verified: package
`io.github.rodos4312.meumobile.preview`, code 9674, 183,252,766 bytes, SHA-256
`9b6eae5fa5dacc51fe21d775ed999998819416962d0f68282435116c790de033`.
Its embedded engine and installer match the hashes for core `245a2db849bf`.
Only the arm64 Flutter engine is present; plugin libraries also contain other
ABIs, so it is not advertised as universal. The source ZIP and handoff are
backed up privately at `Meu-Mobile-private@ef857e7`. The signing certificate
has not been matched to the phone's installed preview. No APK is published,
no installed application is changed and physical-phone acceptance is pending.

- Core Windows regression batch: 28 passed, six host-specific skips across
  transfer, real pairing, PowerShell bootstrap and workflow graph tests.
- The subsequent final transfer/bootstrap batch passed 22 with six skips,
  including reopening the actual profile database to recover the folder grant.
- Real native-owner enrolment and certificate-pinned phone HTTP tests exercise
  both directions, a payload over the earlier 2 MiB JSON ceiling, exact bytes,
  duplicate-name refusal, traversal refusal and grant revocation.
- Fifteen transfer cases run on Windows; the additional symlink/FIFO test is
  explicitly POSIX-only and must be exercised by Linux CI.
- Twelve Desktop UI cases passed, including folder selection/revocation,
  stale previous-profile responses and the pre-existing pairing panel.
- Android: 32 final focused tests passed, whole-production/new-test analysis passed,
  and `:app:compileMeuDebugKotlin` completed offline. New save behavior is source
  compiled, not yet certified on a physical phone.
- Required core source quality: 14 checks passed with zero blocking/advisory
  health findings. Candidate CI and package receipts remain authoritative for
  the final commit and exact artifacts; do not reuse older run conclusions.

## Candidate acceptance

Before installing, verify Android's package ID and signer against the intended
installed preview; never ask for an uninstall that could discard its private
data. Prepare the embedded engine seed from the candidate core commit and
verify its checksums before APK packaging. Keep the native Android and Windows
application/backend revisions recorded together.

Real-phone document picker, cancellation, app close/reopen, background behavior
and paired/autonomous startup still require acceptance on the actual candidate.
Windows update/data-preservation and rollback rehearsals must pass for its exact
package. Extended recovery through an actual Windows OS reboot remains deferred.
Publish nothing and promote no update feed merely because compilation or the
required source checks succeeded.
