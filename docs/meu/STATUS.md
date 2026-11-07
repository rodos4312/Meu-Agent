# Meu development and release status

Current public Windows version: [0.1.0-dev.25](https://github.com/rodos4312/Meu-Agent/releases/tag/meu-v0.1.0-dev.25).
Development and validation take place on `dev/meu-foundation`. The following
changes are candidates for one consolidated release after the remaining checks.

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
| Android provider setup, installation and cleanup | OpenRouter light/strong selection and real install progress remain source-verified. The new seed uses core `17c2fa366872` and physically excludes 16,638 frontend/development files while retaining tools/skills. Native compile, four Python checks and eighteen focused Flutter tests passed; source is backed up privately at `9b3ba72`. [Current runtime checks and limits](ANDROID_RUNTIME_SLIMMING_VALIDATION.md); [earlier provider batch](ANDROID_OPENROUTER_INSTALL_VALIDATION.md). |
| Ordered Coordinator reviews (development only) | Consequential writing tasks use requirements then quality gates; routine/read-only tasks stay light. The later cancellation follow-up fixes queued-helper admission and isolates the intermittent test harness's startup/cleanup. Fifteen capacity cases passed in five fresh runs without retries; actual running-stop checks retain their five-second deadlines. [Current validation](ANDROID_RUNTIME_SLIMMING_VALIDATION.md); [original review scope](COORDINATOR_STAGED_REVIEW_VALIDATION.md). |
| Coordinator on a real provider | Two native detached helpers used `deepseek-flash` and `deepseek-v4-pro` on synthetic payment data. A separate conversation answered while the project was running. Independent checks verified every normalized row and the exact reconciliation result. Both tasks reached verified on their first successful rehearsal attempt. This was a backend rehearsal, not a new Desktop release. |
| Project notes after relocation | 27 focused tests cover real moves, reused paths, independent copies, primary-folder changes, concurrent claims, legacy notes, profile isolation and the notes RPC. Note contents stay in the profile. See [Project memory](PROJECT_MEMORY.md). |
| Native Windows input | Five verified capture, click and Greek Unicode typing rounds against an isolated form. With the installed driver v0.21.0, Ctrl+A did not select all in background delivery; the explicitly targeted foreground retry did. No approval defaults were changed. See [Windows computer use](WINDOWS_COMPUTER_USE_AUDIT.md). |
| Windows installation and recovery | The private rehearsal passed the real NSIS upgrade with data preservation and automatic rollback after a failed startup. Both jobs completed successfully. A retained recovery run across an actual Windows reboot is still unverified. [Private Windows rehearsal](https://github.com/rodos4312/Meu-Agent/actions/runs/42062422358) |
| Consolidated preview release | Pending matching candidate packages and their final acceptance below. Actual Windows OS-reboot recovery remains an explicitly deferred, unverified extended case; do not label it passed or claim full production qualification. Publish the signed update manifest and admitted packages together only after the candidate checks. |

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

1. Exact-source GitHub verification for core `17c2fa366872` completed in
   [run 42424466823](https://github.com/rodos4312/Meu-Agent/actions/runs/42424466823).
   All six required jobs succeeded; three optional distribution jobs were
   skipped. Cancellation's 15 cases passed on the first attempt on both hosts.
   A different Windows bootstrap test exceeded its 30-second PowerShell deadline
   and passed on retry. Investigate `test_generated_windows_pins_match_the_shared_authority`
   before calling CI free from intermittent failures; this batch does not fix it.
   See [runtime validation](ANDROID_RUNTIME_SLIMMING_VALIDATION.md) for the
   cancellation regressions, unchanged actual-stop checks and Android backup.
2. Prepare matching Windows frontend/backend and Android application/runtime
   candidates from recorded revisions. Android's lean seed and installer now
   match admitted engine `17c2fa366872`; asset hashes and native compilation
   passed. Generated assets are not in the source archive: regenerate them
   from the recorded commit before building the consolidated candidate APK.
3. On a physical phone, verify paired-PC and autonomous-phone modes separately:
   the same conversation after close/reopen, actual tools, project creation,
   previews/Save, screen-lock/background behavior and uncertain-send recovery.
   History sync must not be presented as moving execution or project files.
4. Rehearse the final Windows installer/update candidate, preserving chats,
   credentials, project notes, skills and settings. Confirm both app and backend
   revisions and ordinary close/reopen behavior. Keep extended OS reboot tests
   explicitly separate; no installed application is changed by this audit.
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
