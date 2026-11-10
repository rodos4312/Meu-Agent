# Consolidated stability checks — 2026-11-10

Branch: `dev/meu-foundation`. No release, installer or APK is published by this
batch. The prepared dev.30 / Android 9687 binaries predate these changes and
must not be presented as containing them.

## Confirmed cancellation defects

An interrupted project handoff could leave the Android journal in cancellation
because the receiving replica still described an older transfer. Its ready or
released state rejected cleanup of the newer attempt which it had never received.
A paired phone could also not cancel a PC attempt before prepare had arrived,
since the saved receiver was absent or still belonged to an earlier transfer.

The receiver now acknowledges cleanup when it has no incoming staging state for
that attempt and is still remote-owned. It does not change ownership, files or
an active receiving transfer. The authenticated PC route permits cancellation
of an unstarted attempt only while the PC remains the ready owner. Offered
transfers to a different device remain protected. Source cancellation continues
to reject released transfers; there is no timeout-based ownership takeover.

The new real-store regressions failed on the old code in both ready/released
replica cases. The real pinned-HTTPS regression also reproduced the original
403. With the correction, cleanup is repeatable and the next complete handoff
succeeds; a delayed cancellation cannot discard a newer incoming offer. The
same shared core is used by Windows and the Android process bridge.

## Local results

- Baseline: 84 project/history/Coordinator tests passed; one POSIX test skipped
  on native Windows. Includes a real file project, process exit/resume,
  provider-locked routing and ordered requirements/quality review.
- Corrected store and transport suite: 17 tests passed; one POSIX test skipped.
- Android: 85 selected Flutter tests passed across two disjoint suites; one Unix symlink test skipped.
  Covers Auto, independent on-device execution, live observations, reconnect,
  conflict recovery, file transfers, project files, OpenRouter, installation,
  deliverable previews and Coordinator progress/review UI.
- Windows UI: 9 tests passed across project handoff settings, Coordinator
  task criteria and generated deliverable previews.
- All 14 staged-source lint/health checks passed, with no blocking or advisory
  code-health findings.
- Flutter initially failed because the relocated toolchain path contained
  spaces, then because generated localization files were absent. Reusing the
  existing D:/MeuTools aliases and running the existing localization generator
  restored the host test setup. No Flutter upgrade, app state reset or UI
  redesign was needed.

The final pinned-HTTPS run also refuses cancellation of another phone's active
offer. Three Android process-bridge checks pass against the working core;
the updated bridge regression separately fails against the older packaged seed.
Targeted Dart analysis is clean. The new cancellation suite is included in both
Windows and Android-compatibility CI, including their path triggers.

Embedded-engine pin and current CI receipts are recorded
separately before any later candidate rebuild. Older GitHub success applies
only to its recorded revision, not uncommitted changes.

## Acceptance boundaries

No physical Android device is attached. Host fixtures do not establish
screen-lock/background survival, Wi-Fi/mobile-data transition or a physical
PC-off/phone-on project continuation. The earlier actual Windows OS-reboot
trial remains deferred. These limits must survive the final release notes.

Inspect [project handoff](../meu-project-handoff.md) for the explicit transfer
steps and limits. Unsynchronized files cannot be retrieved from a powered-off
device. Host-specific build tools and running processes are not migrated.
The existing single-owner fence, pairing and personal-space checks remain.

[OpenViking review](OPENVIKING_REVIEW.md) is research only and adds no service
to the current Windows or Android installation.
