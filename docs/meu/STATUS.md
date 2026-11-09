# Meu development and release status

Current published Windows version: [0.1.0-dev.28](https://github.com/rodos4312/Meu-Agent/releases/tag/meu-v0.1.0-dev.28).
Development remains on `dev/meu-foundation`; `main` is not changed.

## Consolidated trial delivered — 2026-11-09

Windows **dev.28** and owner-private Android **9684** are published for the
consolidated device trial. Both embedded/source pins are
`2006576aadc3654981baa9d0ac0af829d1d89863`; this status receipt does not rebuild
or replace the delivered packages.

All nine [Windows release gates](https://github.com/rodos4312/Meu-Agent/actions/runs/42662508876)
passed. The native rehearsal upgraded dev.27 to dev.28 and retained fixture
conversation, configuration, API key, memory, skill and desktop zoom. The
separate real-backend upgrade passed. An unpublished dev.29 failure fixture
was rejected and automatically restored the verified dev.28 desktop, real
gateway and pre-update database, retaining the failed state for diagnosis.
It was never a public dev.29 release. A real Windows OS reboot remains deferred.

The installer and unpacked application scans were clean. The downloaded
installer, all release assets, existing Ed25519 signature and actual public
update feed were verified against the measured candidate. There is no paid
Authenticode certificate. Installer SHA-256:
`a6794ac9d6414750eabc67e1ce84c2b502751a723e59e5d8ce9f503474b700a9`.

Android passed 148 Flutter tests (one Unix-only host test skipped), complete
analysis without issues, six metadata/seed/process-bridge checks and real
Flutter-to-PC gateway integration. APK package/version, ARM64 libraries,
original preview signer, unchanged permissions and all embedded runtime hashes
were verified. Sources and measured receipts are preserved in the existing
private Android repository. Install over the existing app; do not uninstall or
clear data. Physical-phone acceptance remains pending, including existing
history/projects, actual tools, multiple devices and Wi-Fi/mobile-data changes.

## Consolidated trial preparation — 2026-11-09

The owner requested an installable **Windows dev.28 / private Android 9684**
trial. Build both from the final reviewed source, retaining the Android preview
package and existing signing certificate. Android 9683 was a frozen local
candidate; its old APK does not contain the later live-conversation changes.

This batch includes shared live PC/phone conversations, reconnect and offline
continuation recovery, unified device management, migration of existing owner
pairings, the Windows Coordinator checkpoint correction, and reusable helper
prompt prefixes. See [release notes](RELEASE-0.1.0-dev.28.md),
[live conversations](../meu-live-conversation.md),
[device migration](../meu-device-management.md) and [Coordinator](COORDINATOR.md).

Core `48d3bbb64859b1cd6e12da13675d0a40c9dfbaf8` passed all six normal
[GitHub validation jobs](https://github.com/rodos4312/Meu-Agent/actions/runs/42658791341).
The source checks do not certify the final installer or APK. The release build
must independently pass package inspection, signature and update metadata
verification, native Windows upgrade and automatic rollback rehearsals.

The phone trial checks in-place update, existing projects and history, full
navigation and Auto, actual tools, multiple devices, file transfer, close/reopen,
screen lock and Wi-Fi/mobile-data reconnect. Genuine divergent offline suffixes
remain an explicit backed-up continuation choice. Project files are not moved
by history synchronization. Personal spaces are not an OS-level tool sandbox.
An actual Windows OS-reboot recovery remains explicitly deferred.

Cache tests demonstrate a longer reusable request prefix without increasing the
prompt text. Real provider cache-hit and cost savings still require measurement;
neither a fixed saving nor a 100% cache-hit rate is promised.

Android is delivered only through the existing owner-private preview lane.
Keep the recorded package/signing identity and install over the existing app;
do not uninstall or clear data. Physical acceptance follows delivery of the
measured test packages and is separate from source/CI verification.

## Historical evidence before the current batch

The sections below retain their original revisions and trial scope. Their older
version numbers and milestones do not supersede the current preparation above.

The current Windows/Android work order is maintained in the
[experience roadmap](EXPERIENCE_ROADMAP.md). It takes precedence over the older
mobile next-trial notes below: Meu Mobile now also has an on-device runtime, and
the recovered Android source is 9673. Historical rehearsal evidence below is
retained with its original scope; it does not certify a newer release.

The 2026-11-07 experience batch completes the source implementation of the
navigation/identity milestone and begins project-location access on both
clients. Local Windows navigation and Android automated checks passed; see
[experience validation](EXPERIENCE_VALIDATION.md). No installer, APK, update-feed
promotion or installed-app change is issued for this batch. Unified deliverables
and in-app file previews are now implemented and locally verified on both
clients; see [deliverables validation](DELIVERABLES_VALIDATION.md) for scope,
test evidence and remaining physical-device/PDF acceptance. Coordinator progress and review receipts are now source-verified on both clients; see [Coordinator visibility](COORDINATOR_VISIBILITY_VALIDATION.md). Selected-owner reconnect and Android cold-start continuity are now source-verified; see [continuity validation](CONTINUITY_VALIDATION.md). The consolidated stability batch corrects cancelled-startup and explicit-stop races; see [stability validation](STABILITY_VALIDATION.md). The local Windows CI replay now completes within the normal per-file limits, preserving its full case coverage. Automated source checks are recorded separately from pending real-device and final-release acceptance.

| Work | Evidence |
| --- | --- |
| Android provider setup, installation and cleanup | OpenRouter light/strong selection and real install progress remain source-verified. Candidate 9674 uses core `245a2db849bf`, with 16,643 frontend/development files physically excluded and tools/skills retained. Native APK build, four Python checks, 32 final Flutter cases and embedded asset inspection passed. Full source backup: `ef857e7`; package receipt: `41b3941`. [Candidate receipt](CONSOLIDATED_PREVIEW_26.md); [historical runtime checks and limits](ANDROID_RUNTIME_SLIMMING_VALIDATION.md). |
| Ordered Coordinator reviews (development only) | Consequential writing tasks use requirements then quality gates; routine/read-only tasks stay light. The later cancellation follow-up fixes queued-helper admission and isolates the intermittent test harness's startup/cleanup. Fifteen capacity cases passed in five fresh runs without retries; actual running-stop checks retain their five-second deadlines. [Current validation](ANDROID_RUNTIME_SLIMMING_VALIDATION.md); [original review scope](COORDINATOR_STAGED_REVIEW_VALIDATION.md). |
| Coordinator on a real provider | Two native detached helpers used `deepseek-flash` and `deepseek-v4-pro` on synthetic payment data. A separate conversation answered while the project was running. Independent checks verified every normalized row and the exact reconciliation result. Both tasks reached verified on their first successful rehearsal attempt. This was a backend rehearsal, not a new Desktop release. |
| Project notes after relocation | 27 focused tests cover real moves, reused paths, independent copies, primary-folder changes, concurrent claims, legacy notes, profile isolation and the notes RPC. Note contents stay in the profile. See [Project memory](PROJECT_MEMORY.md). |
| Native Windows input | Five verified capture, click and Greek Unicode typing rounds against an isolated form. With the installed driver v0.21.0, Ctrl+A did not select all in background delivery; the explicitly targeted foreground retry did. No approval defaults were changed. See [Windows computer use](WINDOWS_COMPUTER_USE_AUDIT.md). |
| Windows installation and recovery | The private rehearsal passed the real NSIS upgrade with data preservation and automatic rollback after a failed startup. Both jobs completed successfully. A retained recovery run across an actual Windows reboot is still unverified. [Private Windows rehearsal](https://github.com/rodos4312/Meu-Agent/actions/runs/42062422358) |
| Consolidated preview release | Windows dev.26 draft and local Android 9674 candidate prepared; all nine Windows CI jobs passed, including native upgrade and automatic rollback. Physical-phone and owner acceptance remain below. Actual Windows OS-reboot recovery remains deferred and unverified; no full production qualification or automatic publication is claimed. |

The public installer and update feed are the release authority. Ed25519 manifest
verification already operates without a paid certificate; Windows publisher
signing is not a requirement for this distribution. See [Release retention](RELEASE_RETENTION.md)
for which versions remain available. No old repository, tags, or source history
are removed by the maintenance pass.

The disposable hosted Windows probe established the pre-reboot handoff, but
[run 42063092869](https://github.com/rodos4312/Meu-Agent/actions/runs/42063092869)
timed out without an authenticated receipt from a later OS boot. This does not
establish whether Meu recovery passed or failed. The experimental workflow is
retained in Git history and removed from active workflows. The remaining check
needs an isolated Windows guest that stays available through a real restart,
with evidence that the retained updater restored the app, backend and test data.
No host restart or Windows feature change was performed.

## Current acceptance before the consolidated preview

1. The frozen Windows `0.1.0-dev.26` candidate is core `48cd8daf689b` in
   [run 42429977825](https://github.com/rodos4312/Meu-Agent/actions/runs/42429977825).
   All six required jobs passed. The bootstrap test's cold PowerShell budget
   now matches its sibling checks at 60 seconds; all seven native cases passed
   with zero file retries. Windows transfers passed 15 cases (one host skip),
   Linux passed all 16, and real Windows pairing passed four. The earlier
   connection-form mock failure was corrected and the exact failed group
   passed 82 cases locally before this final CI. See the
   [candidate report and owner trial](CONSOLIDATED_PREVIEW_26.md).
2. Windows installer packaging, package scans, launch, update signature and
   native upgrade from public dev.25 passed. Automatic rollback and draft
   admission also passed in that same run. Android private preview 9674 was
   assembled; its embedded lean seed and installer match engine `245a2db849bf`.
   Subsequent Windows revisions change only tests, CI and documentation, with
   identical production transfer code. Android passed 32 final Flutter cases,
   whole-production analysis, native compilation and asset checksum inspection.
   The full source is backed up privately at `Meu-Mobile-private@ef857e7`.
   Its APK remains local/private and the installed phone signer match is
   unverified; do not uninstall the existing preview or discard its data.
3. On a physical phone, verify paired-PC and autonomous-phone modes separately:
   the same conversation after close/reopen, actual tools, project creation,
   previews/Save, screen-lock/background behavior and uncertain-send recovery.
   History sync must not be presented as moving execution or project files.
4. Preserve the final Windows installer/update and recovery receipts, then
   confirm app/backend revisions and ordinary close/reopen behavior during the
   owner trial. Keep extended OS reboot tests explicitly separate; no installed
   owner application is changed by candidate preparation.
5. Run a representative real-model project through both review stages, then
   prepare matching screenshots, release notes, download links and verified
   update metadata. Deterministic fixtures prove orchestration, not LLM judgment.

Unconfigured outside-home connectivity without a separate VPN, a production
self-evolution optimizer, a new MemOS service stack, swarm cleanup and a Rust
rewrite are not silently added to this preview. They remain separate design
or acceptance work. See [shared-memory research](COMMUNITY_SHARED_MEMORY_REVIEW.md)
for the proposed local project-knowledge handoff and community comparisons.

## Historical mobile trial notes

The notes below describe the earlier companion milestone. The current roadmap
and acceptance list above take precedence; an autonomous Android source now
exists and must be validated with its own engine package.

1. Test the built-in Android QR pairing on a physical phone against the matching
   Windows preview. The Windows gateway rehearsal completed a Greek test
   message using a loopback model fixture, rejected a repeated pairing
   challenge, replayed the same run and revoked the phone's access. See the
   [Android companion plan](ANDROID_COMPANION.md).
2. Upgrade an existing desktop installation with the Windows trial distribution.
   Verify that projects, notes, and settings open as expected and the installed
   version matches the update feed.
3. Run a real project with the Coordinator. Check that each helper's assignment,
   progress, verification result, and deliverables are easy to find. Group fixes
   from this trial into a maintenance release.
4. Extend the Android companion with authenticated QR pairing on the same
   Wi-Fi network and a versioned gateway
   adapter. The desktop runs the work. The phone opens the paired profile's
   projects, sends messages, follows helper progress, and opens deliverables.
   Test reconnecting without duplicate messages and revoking a phone's access
   from the desktop before moving on to voice and access away from home. See the
   [Android companion plan](ANDROID_COMPANION.md) for the first end-to-end test.

An independent Android edition is a later decision if users need to run tasks
while the desktop is off. The MT5 connector remains a separate workstream that
starts with monitoring and reading data. Order execution is a separate stage.

For reproducible opt-in checks, see `scripts/meu/coordinator_live_probe.py` and
`scripts/meu/computer_use_live_probe.py`. The former makes real requests to the
selected model provider. The latter runs only on Windows and only targets the
fixture it launches. Their outputs belong in a fresh local directory, not in Git.

The foundation audit, early updater notes and removal ledger preserve historical
decisions. Use this page for the current backlog and the feature guides for behavior.
