# Meu development and release status

Current public Windows version: [0.1.0-dev.22](https://github.com/rodos4312/Meu-Agent/releases/tag/meu-v0.1.0-dev.22).
Development and validation take place on `dev/meu-foundation`. The following
changes are candidates for one consolidated release after the remaining checks.

| Work | Evidence |
| --- | --- |
| Coordinator on a real provider | Two native detached helpers used `deepseek-flash` and `deepseek-v4-pro` on synthetic payment data. A separate conversation answered while the project was running. Independent checks verified every normalized row and the exact reconciliation result. Both tasks reached verified on their first successful rehearsal attempt. This was a backend rehearsal, not a new Desktop release. |
| Project notes after relocation | 27 focused tests cover real moves, reused paths, independent copies, primary-folder changes, concurrent claims, legacy notes, profile isolation and the notes RPC. Note contents stay in the profile. See [Project memory](PROJECT_MEMORY.md). |
| Native Windows input | Five verified capture, click and Greek Unicode typing rounds against an isolated form. With the installed driver v0.21.0, Ctrl+A did not select all in background delivery; the explicitly targeted foreground retry did. No approval defaults were changed. See [Windows computer use](WINDOWS_COMPUTER_USE_AUDIT.md). |
| Windows installation and recovery | The private rehearsal passed the real NSIS upgrade with data preservation and automatic rollback after a failed startup. Both jobs completed successfully. A retained recovery run across an actual Windows reboot is still unverified. [Private Windows rehearsal](https://github.com/rodos4312/Meu-Agent/actions/runs/42062422358) |
| Consolidated release | Pending the post-reboot recovery check and validation of the final candidate. Only then build and publish the signed update manifest and Windows installer. |

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

## Next trial steps

1. Build and try the Android chat preview against a dedicated HTTPS Meu test
   gateway. See the [Android companion plan](ANDROID_COMPANION.md).
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
