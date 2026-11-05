# Meu development and release status

Current public Windows version: [0.1.0-dev.22](https://github.com/rodos4312/Meu-Agent/releases/tag/meu-v0.1.0-dev.22).
Development and validation take place on `dev/meu-foundation`. The following
changes are candidates for one consolidated release after the remaining checks.

| Work | Evidence |
| --- | --- |
| Coordinator on a real provider | Two native detached helpers used `deepseek-flash` and `deepseek-v4-pro` on synthetic payment data. A separate conversation answered while the project was running. Independent checks verified every normalized row and the exact reconciliation result. Both tasks reached verified on their first successful rehearsal attempt. This was a backend rehearsal, not a new Desktop release. |
| Project notes after relocation | 27 focused tests cover real moves, reused paths, independent copies, primary-folder changes, concurrent claims, legacy notes, profile isolation and the notes RPC. Note contents stay in the profile. See [Project memory](PROJECT_MEMORY.md). |
| Native Windows input | Five verified capture, click and Greek Unicode typing rounds against an isolated form. With the installed driver v0.21.0, Ctrl+A did not select all in background delivery; the explicitly targeted foreground retry did. No approval defaults were changed. See [Windows computer use](WINDOWS_COMPUTER_USE_AUDIT.md). |
| Windows installation and recovery | [Windows CI 42039627692](https://github.com/rodos4312/Meu-Agent/actions/runs/42039627692) verified installation, upgrade, automatic rollback, matching application registration and preservation of local data on real NSIS installs. Difficult process-failure cases are recorded in [Distribution and updates](DISTRIBUTION_AND_UPDATES.md). A retained recovery run across an actual Windows reboot is still unverified. |
| Consolidated release | Pending the post-reboot recovery check and validation of the final candidate. Only then build and publish the signed update manifest and Windows installer. |

The public installer and update feed are the release authority. Ed25519 manifest
verification already operates without a paid certificate; Windows publisher
signing is not a requirement for this distribution. See [Release retention](RELEASE_RETENTION.md)
for which versions remain available. No old repository, tags, or source history
are removed by the maintenance pass.

For reproducible opt-in checks, see `scripts/meu/coordinator_live_probe.py` and
`scripts/meu/computer_use_live_probe.py`. The former makes real requests to the
selected model provider. The latter runs only on Windows and only targets the
fixture it launches. Their outputs belong in a fresh local directory, not in Git.

The foundation audit, early updater notes and removal ledger preserve historical
decisions. Use this page for the current backlog and the feature guides for behavior.
