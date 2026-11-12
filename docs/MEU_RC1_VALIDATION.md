# MEU vNext RC1 — validation record

Validation date: 2026-11-12. Branch `dev/meu-foundation`. This was release engineering only; no feature
work was done. Nothing was published, pushed or merged, and the production installation was not modified.

## Build identity

| Item | Value |
|---|---|
| Version | `0.1.0-dev.34` (MEU vNext RC1; the existing `0.1.0-dev.N` scheme) |
| Source commit | `f57ea5be88e0d8a66889931a5035bed7d001ae2c` (maintainability pass) |
| Build id (launch identity) | `0.1.0-dev.34+gf57ea5be88e0-dirty@2026-11-12T18:19:57.383Z` |
| Build date | 2026-11-12T18:19:57Z |
| Installer | `apps/desktop/release/Meu-0.1.0-dev.34-win-x64.exe`, 147,997,353 bytes, SHA-256 `1b997ec20545278944d69cff26140635e1215707888941018601ceb97b2a97c5` |
| Update channel | `rodos4312/Meu-Agent`, channel `meu-preview`, `releaseType: draft`, Ed25519 key `MCowBQYDK2VwAyEAYd0zfWzggoBhp4krGDFhEQzjy1/l59ZxXNLT/cqmGTw=` |
| Migration versions | config `_config_version` 52, SessionDB schema 32, semantic store `"2"`. Production is already at 52 and 32, so no schema migration runs. |

**Why the stamp is `-dirty`:** the only uncommitted change is the version bump (`apps/desktop/package.json`,
`package-lock.json`). A release build must be rebuilt after the `release(meu): prepare 0.1.0-dev.34` commit.

**Why the builder exited 1:** after writing the installer and blockmap, electron-builder tried to create its
GitHub publisher and found no `GH_TOKEN`. This happens only in the local environment; nothing was uploaded.

**Payload check:** the installer payload (`app-64.7z`) is byte-identical to `release/win-unpacked`
(1,211 files, 428 MB), plus `Uninstall Meu.exe`.

## Install paths

- **Production install, left untouched:**
  - app at `%LOCALAPPDATA%\Programs\Meu` (0.1.0-dev.33, commit `bac9e282`);
  - data at `%LOCALAPPDATA%\MeuAgent` and `%APPDATA%\Meu`.
- **RC1 side-by-side:** `D:\meu-work\.cache\rc1\install-rc1` (the extracted installer payload). Each test
  had its own `MEU_HOME`/`HERMES_HOME` and `HERMES_DESKTOP_USER_DATA_DIR` under `D:\meu-work\.cache\rc1\`.
  The backend was the RC1 source checkout (`HERMES_DESKTOP_HERMES_ROOT`) with
  `HERMES_DESKTOP_ISOLATED_BACKEND=1`.
- **Why the NSIS installer was not executed on this machine:** it is per-user with the same appId as
  production. It reads the existing HKCU registration and uninstalls that installation first, whatever
  `/D=` path is given. Running it here would remove production. The repository's own install, upgrade and
  rollback rehearsals refuse to run outside a disposable GitHub runner for the same reason.
- **Proof that production is untouched:**
  - all 473 production state files have the same hashes as before the tests;
  - all 1,215 production install files are unchanged;
  - the registry still reads `Meu 0.1.0-dev.33`.

## Migration path

1. **Read-only snapshot** of production into `.cache/rc1/snapshot` (471 files, 34 MB): config, `state.db`
   (34 sessions, 1,584 messages), `projects.db`, `shared-state.db`, kanban, memories, skills, cron, pairing,
   telemetry and the small userData JSON files.
   - Every source file was hashed before and after copying; 0 changed.
   - Secrets were never copied. `.env`, `auth.json` and connection tokens were rewritten with fake values;
     only the 12 key names were kept.
2. **Migration run:** RC1 was launched on a copy of the snapshot. Compared with the snapshot:
   - Identical: config (same digest), env key names, auth providers, sessions and messages (same digests,
     so original timestamps and 0 duplicates), memories, projects, pairing, `install_id` and userData.
   - Changed, as expected: bundled skills were synced to the RC1 commit (the Phase 8 Nous comment removal
     reached `gws_bridge.py`), and the cron/heartbeat files.
3. **Legacy settings stay inert.** A copy was given `model.provider: nous`, `NOUS_API_KEY`,
   `web.use_gateway: true` and `browser.cloud_provider: nous`. RC1 then:
   - shows "Unknown provider 'nous'" and the provider-setup screen;
   - strips `NOUS_API_KEY` from child environments;
   - blocks a coding task ("Plan refused"), with **no network attempt**;
   - shows no Nous provider anywhere in the UI.
4. **Stale project memory:** coding memory is advisory and the repository stays authoritative. This is
   covered by the `tests/meu_coding/test_coding_memory.py` stale-note tests (passed). Production had no
   coding memory or coding history to migrate, because the Coding Engine is new since dev.33.

## Upgrade and rollback

The upgrade was emulated on disposable copies, following the updater's order: stop the gateway, keep the
previous app and a profile backup as rollback artifacts, replace the app files, then launch.

- **Upgrade (dev.33 → RC1)** used a copy of the installed dev.33 with a dev.33 backend on the snapshot
  profile.
  - The first RC1 launch connected in 29.5 s (with "code changed to f57ea5be88e0" maintenance); the second
    in 4.1 s.
  - Version reported: 0.1.0-dev.34. One gateway per profile.
  - All user data was preserved: the same digests as above.
- **Failed upgrade** (controlled RC1 startup failure):
  - The UI shows "Meu couldn't start … Nothing here deletes your chats or settings" with Retry, Repair
    install, Gateway settings and Open logs.
  - No profile data changed.
- **Rollback R1** (dev.33 restored onto the failed-upgrade profile): healthy, and the data is identical to
  before the upgrade.
- **Rollback R2** (dev.33 on a profile RC1 had already used, including coding tasks): healthy. The coding
  audit files are kept and the bundled skills return to dev.33.
- **Not tested on this machine:**
  - the real NSIS handoff;
  - the signed-manifest update through the updater;
  - the backend bootstrap from GitHub.

  All three need the commit pushed and a disposable runner (`verify_upgrade`).

## Tests and checks

**Baseline at `f57ea5be`:**
- `tests/meu_coding` passed (see the maintainability-pass record), along with the mobile coding, coding RPC
  and contracts suites.
- Failures that already exist on HEAD:
  - 2 cases in `test_config` (`TestEnvWriteDenylist`);
  - 36 POSIX-only `tests/e2e/core/upgrade` modules, which need `pwd` and run on Linux CI.
- Desktop and TUI typecheck: clean. `scripts/check`: 14/14 ok. eslint on `src/plugins/meu-coding`: clean.
- Full desktop eslint (`src/ electron/`) reports 129 style errors (`curly`, `perfectionist/sort-*`) outside
  `meu-coding`. They already exist on HEAD: no TS file changed in this step.

**Packaged RC1:**

| Check | Result |
|---|---|
| Brand identity | PASS |
| Updater: trusted-key channel check and forged-release refusal | PASS (2 launches) |
| `app.asar` scan | 0 Nous patterns |

**Coding Engine health-check on the upgraded profile.** This uses the real RC1 backend code; only the model
answers are scripted.
- Route resolution from the profile config.
- A forged fingerprint is refused; a valid approval is accepted.
- Execution runs in an isolated worktree; 3/3 real checks pass; the parent checkout is untouched.
- Keep leads to a commit preview with a token; Reject removes the worktree.
- After a restart the kept task restores as `ready_to_commit`, and the pending approval expires.
- The audit holds no secrets.

**Failure cases**, all non-destructive:
- **Interrupted first start:** the stale pid/lock is recovered.
- **Hard crash after migration:** the relaunch connects in 4 s.
- **Invalid `config.yaml`:** the file is not overwritten (see Known limitations for the UI side).
- **Corrupt temp/cache files:** rewritten.
- **Corrupt coding audit record:** skipped; the file is kept on disk.
- **Missing provider:** "No coding model is configured — choose a main model or Models by workload in
  Settings."

**Coexistence:**
- An older Meu (separate home) and RC1 run at the same time with separate backends.
- A second RC1 process on the same profile hands off and exits in 0.3 s (one window).
- One gateway per home; `hermes gateway stop` works with 4 concurrent gateways.

## Performance (this machine, isolated profiles)

| Measure | RC1 | dev.33 |
|---|---|---|
| Cold first launch, new profile (renderer / backend) | 7.2 s / 32.3 s | — |
| Warm start (renderer / backend) | 1.7–1.8 s / 3.9–4.3 s | 1.7 s / 4.0–4.2 s |
| First launch after a code change on the migrated profile, no MCP | 26.5–37 s | 70 s+ (passed the 60 s desktop deadline) |
| Coding page open / task list loaded | 43–62 ms / 1.3–3.5 s | no Coding page |
| Coding task: start → approval request (scripted model) | 1.0 s first, 0.55 s repeated | — |
| Approval → executed + 3 real checks + diff review | 54 s (includes worktree creation and runtime preparation on first use) | — |
| Restart restore of coding tasks | 0.03 s | — |
| Repo index of this 21,766-file repository (cold / cached) | 29.3 s / 9.7–10.9 s | — |
| 1-file refresh; repeated context query | 0.06 s; 0.07–0.44 s | — |

Rendering approval and diff for a **live** task in the desktop UI needs a real model. This is pending the
controlled real update test.

## Storage behaviour

**Bounded:**
- Config backups: one `config.yaml.good.*`, not one per launch.
- Logs: rotating; under 100 KB after the test runs.
- Extraction cache: pruned to live paths.
- Semantic store: rebuilt when the schema changes; one per project.
- Worktrees: Reject removes them. Idle trees are swept every 6 h (24 h / 72 h tiers). Archive refs
  `refs/hermes/archive/*` are deleted after `worktrees.archive_retention_days` (30).

**Kept by design:**
- Coding audit records (a few KB per task, the recovery trail).
- The `tools/` runtime downloaded on the first launch of a profile (318–715 MB in the test profiles; 1.98 GB
  in production).

**Notes:**
- After a Reject, the worktree branch ref `hermes-subagent/subagent-coding-*` and an archive ref remain in
  the user's repository until the sweep removes them.
- Test artifacts live in `D:\meu-work\.cache\rc1`, which is gitignored. They include copies of the
  production chat history, without secrets; delete the folder after review.

## Security review

**Verified:**
- No fake secret value appears outside `.env`/`auth.json` in any test profile, log or audit file.
- No Nous URL appears in any log. No telemetry change: the telemetry tree digest is unchanged.
- No Nous provider in the UI or the package. `NOUS_API_KEY` is stripped from child environments, and the
  legacy provider makes no network call.
- Approvals are still required: a forged fingerprint is refused, and an expired approval never resumes.
- Worktree isolation is intact: the parent checkout was untouched.
- Remote mutation stays gated: the `test_remote_attacks` / `test_remote_flow` suites pass.
- Migration copies no secrets into other locations.

**Found during testing:**
- On first start, a migrated copy launches the user's **configured MCP servers** (`D:\Meu-Market`
  read-only server, `rea` via npx), which is expected config behaviour. For the remaining tests these were
  disabled in the test copies, and the processes that had started were stopped.

## Android

- **APK:** `apps/android/out/Meu-Android-preview.apk`.
  - Built with `build-preview.sh` (the fixed Windows `.bat` path) using the existing JDK 17 / SDK 35
    toolchain at `D:\meu hermes meu\.meu-mobile-tools`. A temporary junction avoided the spaces in that path.
  - Package `io.meuagent.preview`, `versionName` `0.1.0-preview.6`, `versionCode` 6, target SDK 35, label
    "Meu Preview".
  - Signature v2 and v3 (one signer, CN=Meu Android Preview, SHA-256
    `ce65881af340f9f9ee8bf67ccbc41bfbc2189594a53009a6dcd9c422d29893d2`).
  - APK SHA-256 `8d6bec2a4702c9a5a318a8c1769d3e6e1442f295ac47c3e046c717e7e9528f61` (459,312 bytes).
  - The zip integrity test, the pairing/TLS tests embedded in the build, and the HTTPS endpoint tests passed.
- **Compatibility:** 87 gateway mobile tests passed (pairing, device migration, relay, live, coding
  approvals). Pairing codes are compatible (the server issues `meu2`; the app accepts `meu1`/`meu2`/`meu3`).
  The coding endpoints are additive, so an older app works with RC1.
- **Real device:** none connected. **Real-device validation is pending.**

## Known limitations

1. **First launch after an update:** with production's MCP servers configured, the first backend start can
   take longer than the 60 s desktop deadline and show "Meu couldn't start". Retry or a relaunch connects.
   dev.33 shows the same deadline behaviour (70 s+), so this is not an RC1 regression.
2. **Invalid `config.yaml`:** the backend falls back to `.env` values. The log warns clearly, but the UI
   shows no config error.
3. **Retired provider message:** for an unknown provider id (e.g. a legacy `nous`), the remedy text says
   "Set the NOUS_API_KEY environment variable", from the generic message for unknown providers. The
   provider cannot be activated, but the wording should say that the provider is retired.
4. **New Android app against an older PC (dev.33):** coding calls show "This coding task is no longer on
   your PC." instead of a version-mismatch message.
5. **Preview APK signing:** each build uses a new signing key with the same `versionCode`, so a phone needs
   uninstall/reinstall to move between preview builds.
6. **Coding routes in production:** the production config enables smart routing without workload slots, so
   every coding role (the Reviewer included) uses the main model (`deepseek-flash`). Configure a `complex`
   slot before relying on the Reviewer.
7. **Upgrade emulation only:** the real NSIS, updater and GitHub backend bootstrap path was not run here
   (see Upgrade and rollback).
8. **Live approval/diff rendering** in the desktop UI with a real model was not exercised.

## Open release-engineering items (second pass, 2026-11-12)

### 1. NSIS upgrade/rollback: blocked locally, CI path requires a push to `dev/meu-foundation`

- **Locally:** no safe disposable Windows environment exists.
  - Windows Sandbox is not enabled, and enabling it is a system change.
  - No VM.
  - The real installer would uninstall production (shared appId).
  - A test-identity build would be a bundled channel build, which is a different artifact from RC1.
- **In CI:** the existing workflow (`meu-windows-validation.yml`, `verify_upgrade`) and
  `meu-rollback-rehearsal.yml` run the real NSIS upgrade, the startup-failure rollback and the interrupted
  install. They only run for `rodos4312/Meu-Agent` on `dev/meu-foundation` (or a `meu-release-request-*`
  tag), and they require the commit to be an ancestor of `origin/dev/meu-foundation`. A test branch or a
  test repository is refused by design.
- `origin/dev/meu-foundation` is at `bac9e282` (dev.33). The RC1 commits are local only.

### 2. Signed release build: blocked

- MEU does not sign the EXE with Authenticode. Release trust is the Ed25519-signed `meu-release.json`
  manifest, and `prepare-meu-release.mjs` requires the installer to be `NotSigned` on this path.
- The private key exists only as the Actions secret `MEU_RELEASE_PRIVATE_KEY`. This environment has no
  `.meu-tooling/meu-update-key` and no environment key. It was not searched for elsewhere.
- The manifest also requires a clean stamp: the version bump must be committed.
- Done locally with the existing `scan-meu-package.ps1`:
  - Defender scans of the installer and `win-unpacked`: **clean**, exit 0, no threats.
  - Product version `0.1.0-dev.34`; SHA-256 matches the build; Authenticode `NotSigned`, as expected.

### 3. Android device/emulator: blocked

- No device is connected (`adb devices` is empty).
- No emulator, system image or AVD is installed, and installing one was not approved.
- Not validated on a device:
  - install, launch and update over the previous APK (the key differs per build);
  - pairing and reconnect, background/foreground;
  - coding approval, stale-approval rejection, Keep/Reject;
  - sync continuity and restart recovery.

### 4. Updater / GitHub backend

The existing CI test groups ran locally on RC1:

| Group | Result |
|---|---|
| Release origin, signatures, update recovery (`meu-release-feed`, `meu-signature`, `meu-windows`, `meu-recovery`, `meu-client`, `meu-prepare`, `meu-rollback`, `operation`, `prepare-meu-release`, `write-build-stamp`, `meu-release-maintenance`) | 92/92 |
| Installed-home isolation and upgrade setup | 38/38 |
| Update notification and consent | 126/126 |
| Cancelled startup and installer recovery, gateway stop before update, update gate/order | 83/83 |
| `tests/scripts/install/test_meu_*` | 3/3 |

The packaged RC1 refused a forged release before download (see above).

**Critical finding:** a real RC1 installation bootstraps its backend at the pinned commit through
`scripts/install.ps1`, which requires `merge-base --is-ancestor <commit> origin/dev/meu-foundation`. Until
`f57ea5be` (plus the version commit) is on `origin/dev/meu-foundation`, a real install or update to RC1
fails at "commit … is not on branch". The local side-by-side tests passed only because the backend came
from the source checkout.

**Not run:**
- real release-metadata lookup and download from GitHub for RC1;
- the native NSIS handoff;
- automatic rollback after a failed real update.

All three need the CI path below.

### Steps that need explicit approval, in order

1. Commit the version bump with a non-release title, so no draft release is created.
2. Push `dev/meu-foundation` to `origin`. This publishes the Phase 2–8 and maintenance commits.
3. Dispatch "Meu Windows validation" with `verify_upgrade=true`. It runs:
   - the real NSIS upgrade from the newest public baseline;
   - the backend upgrade;
   - forged-manifest and tampered-installer refusal;
   - the startup-failure rollback.
4. Dispatch "Meu rollback diagnostic" with that run id: `guardian-loss`, `locked-package` and
   `interrupted-install` (a failure in the middle of the update).
5. Only after both are green: `release(meu): prepare 0.1.0-dev.34`, which produces a signed **draft**
   prerelease. Publishing it is a separate manual step.

## Production install status

Unchanged: 0.1.0-dev.33 (`bac9e282`) at `%LOCALAPPDATA%\Programs\Meu`, with its data at
`%LOCALAPPDATA%\MeuAgent`. It was not running during the validation and was never pointed at by RC1.
