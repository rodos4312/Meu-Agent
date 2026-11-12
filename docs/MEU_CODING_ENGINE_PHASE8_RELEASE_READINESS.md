# MEU Coding Engine — Phase 8: Release Readiness (MEU vNext RC1)

Date: 2026-11-12. Branch `dev/meu-foundation`, base commit
`ab387d15c87888a212431b59e62fbcaf171df427` (Phase 7). Phase 8 is hardening, cleanup and
validation only: no feature work. Nothing in this phase is committed, pushed or merged.

Priority order applied: stability → security → recovery → install/update → correctness →
performance → release readiness.

---

## A. Summary and verdict

| Area | State |
|---|---|
| Desktop Vitest (16,540 tests) | 16,296 passed; 2 environment-only failures remain (§B). Baseline was 94 failures. |
| Python core suite (MEU coding engine) | 416 / 416 |
| Python regression + Phase 8 touched areas (81 files) | 1,339 passed; 6 failures, all present on the base commit or host privilege (§O) |
| Typecheck (4 projects), production build, `scripts/check` (14) | Clean |
| ESLint | No error in any file this phase touched; 129 errors in 34 untouched files pre-exist on the base commit |
| RC1 package | Built; two isolated packaged launches pass; no Nous domain or brand string in `app.asar` |
| Android preview APK | Builds and verifies (v2 + v3 signatures); **no device available — not validated on hardware** |
| Real NSIS upgrade / rollback rehearsal | **Not run locally** (would overwrite the production registration); covered by unit tests and the CI workflow |
| Nous removal | Runtime, UI, i18n and wire contract cleaned; remaining references listed in §K |

**Verdict: GO for an internal RC1 (developer validation), NO-GO for a public release** until the
three open items in §Q are closed: the CI `verify_upgrade` rehearsal on a disposable Windows runner,
an Android on-device check, and a clean committed, signed build (the RC1 here is built from an
uncommitted working tree and is therefore not a distributable artifact).

---

## B. Full desktop failure triage, by root cause

Quiet baseline at the start of Phase 8: 94 failing tests in 43 files (101 under concurrent load).
Final run (CI-equivalent: `HERMES_PYTHON` set, `uv` on PATH): **6 failing tests in 9 files on the
loaded full run, 2 after the fixes below.**

| Root cause | Tests | Resolution |
|---|---|---|
| Real product bugs | 3 | Fixed: product-identity channel token (a stable-branded Meu channel got its own userData); `payload-sign-cache.mjs` missing `-ExecutionPolicy Bypass`; Android preview build leaking its work dir and throwaway keystore |
| Interpreter not provided (`python3`, `uv`) | 6 files | Environment: run with `HERMES_PYTHON` and `uv` on PATH, as CI does |
| Windows symlink privilege | 14 | Gated on a real capability probe (`electron/test-symlink-capability.ts`), not on the OS name |
| PowerShell execution policy in test harnesses | 6 | Harness passes `-ExecutionPolicy Bypass`, as the product already does |
| POSIX- or Linux-only behaviour | 13 | `runIf` host gates with a "Host-specific:" reason on each |
| Stale fixtures (Meu release files, branch, stamps, CRLF, locale) | 15 | Fixtures updated to the Meu release layout |
| Intentional Meu product changes (branding, removed Nous billing/catalog download) | 29 | Tests rewritten to Meu behaviour; obsolete `catalog-download.test.ts` removed (covered by `catalog-data.test.ts`) |
| Load-sensitive timeouts | 4 | Explicit, commented timeouts; `packaged-working-directory` cleanup now retries the asynchronous Windows handle release |
| `i18n` key index stale after key removal | 1 | Regenerated `locales/_keys.desktop.json` |
| **Remaining — host policy** | 1 | `commit-bundles.windows`: `makeappx.exe` is blocked by this machine's security policy. No security setting was changed. |
| **Remaining — not a Vitest test** | 1 file | `side-by-side.windows.test.mjs` is a native SDK proof run with `node`; it cannot load under Vitest's module evaluator (also failing on the base commit) |

Load-flaky files observed only under parallel load and passing in isolation:
`plugin-files-spellings`, `probe-prepared-native`, `linux-nvidia-egl-recovery.native`,
`browser-hints`, `file_read_guards` (Python).

## C. `test_docs_drift` and `test_prompt_surface`

- Docs drift: the missing keys were confirmed against the real config surface before documenting
  them (gateway lifecycle and media delivery, `smart_model_routing.enabled`, `approvals.approvers`)
  in `website/docs/user-guide/configuration.md`. Passes.
- Prompt surface: the Windows render failed for two harness reasons (missing `USERPROFILE`, psutil's
  Linux backend loaded under the Linux platform pin); both fixed in `scripts/ci/prompt_surface.py`.
  The regenerated fixtures were reviewed line by line: the only content changes are intentional Meu
  changes (identity "You are Meu", Meu docs URL, skills guidance, the `project` memory target,
  `manage_connections`, `tool_search`). Passes.

## D. Windows install, update and rollback

The production install (`%LOCALAPPDATA%\Programs\Meu`, 0.1.0-dev.33, appId `com.meuagent.desktop`)
was not touched: its `Meu.exe` was last written 2026-11-11, before this phase. An NSIS install of
any RC with the same appId would replace that registration and its shortcuts, and Windows Sandbox
is not available on this host, so:

- **Run locally:** every updater, recovery, rollback, signature and state-DB preflight unit test
  that `meu-windows-validation.yml` lists (all part of the passing Vitest run); the packaged-app
  isolation test (§E), which drives the real packaged updater against its signed channel and
  rejects a forged release before download.
- **Not run locally:** `test-meu-native-upgrade` and `test-meu-rollback` (real NSIS upgrade and
  rollback). They need a disposable Windows runner: `meu-windows-validation.yml` /
  `verify_upgrade=true`. Required before any public release.

## E. RC build — MEU vNext RC1

| Field | Value |
|---|---|
| Name | MEU vNext RC1 |
| App version | `0.1.0-dev.33` (unchanged; no version bump in this phase) |
| Build | `npm run pack` (unpacked `--dir`, `--publish never`), 2 min 24 s |
| Output | `apps/desktop/release/win-unpacked/Meu.exe` (246,858,752 bytes) |
| Source commit | `ab387d15c87888a212431b59e62fbcaf171df427` + uncommitted Phase 8 tree (`dirty: true` in the stamp) |
| Built at | 2026-11-12T10:06:38Z |
| Update channel | `rodos4312/Meu-Agent`, `dev/meu-foundation`, `meu-preview`, free Ed25519 key present |
| Signature | Unsigned (no Authenticode key on this host) |
| Config schema | 52 (unchanged) · state.db schema 32 (unchanged) · semantic index schema 2 (unchanged) |

Isolated launch test (`scripts/test-meu-installed.mjs`, scratch `MEU_HOME`, `HERMES_HOME` and
userData, fake backend): two launches pass — renderer, "Set up Meu", no usage-stats prompt, app name
`Meu`, isolated paths, update check against the Meu channel with the trusted key, forged release
rejected. Identity smoke (`test-meu-brand.cjs`): PASS. Byte scan of `app.asar`: 0 occurrences of
`nousresearch.com`, `portal.nousresearch`, `inference-api.nousresearch`, `Nous Portal`,
`Nous Research`, `NousResearch/hermes-agent`.

`prepare-meu-release.mjs` refuses this build by design (dirty tree). A distributable RC needs a
committed tree and the release lane.

## F. Migration tests

New `tests/meu_coding/test_upgrade_migration.py` (5 tests, pass): Phase 4 audits restore without
resuming; Phase 6 remote history never re-pushes; Phase 7 roadmaps missing optional fields load; an
old semantic schema is rebuilt; a profile upgrade keeps settings and memory and never logs a key.
Added this phase: an auto-seeded `SOUL.md` with the upstream identity ("You are Hermes Agent, built
by Nous Research") is upgraded in place to Meu's; a user-edited file is never touched.

## G. Android

`apps/android/build-preview.sh` with the official SDK layout: build rc=0; ZXing checksum,
`MeuEndpointTest` and `MeuPairingTest` pass; aapt2, javac, d8, zipalign, `unzip -t` OK; apksigner
verifies v2 + v3. Package `io.meuagent.preview` 0.1.0-preview.6, targetSdk 35, 459,312 bytes.
**No device or emulator is available: install, pairing and runtime behaviour on hardware are not
validated.** Each preview build signs with a fresh key, so it cannot upgrade in place over an earlier
preview APK.

## H. Performance (Windows, this repository, 21,783 files)

| Measure | Phase 7 | Phase 8 |
|---|---|---|
| Structural index, cold | 24–28 s | 28.1 s |
| Cached startup (structural) | 24.3–26.0 s* / 9.6 s (Phase 1) | 10.6 s |
| 1-file / 10-file refresh (paths given) | 0.06 / 0.38 s | 0.05 / 0.45 s |
| Context query, repeated | 0.07–0.35 s | 0.08–0.52 s |
| Semantic initial index | 204 s | 206 s (94,860 chunks) |
| Cached startup, structural + semantic | 24.8–27.1 s | 27.0 s |
| Semantic 1-file / 10-file refresh | 19–21 / 75–114 ms | 20 / 96 ms |
| Semantic query median / first | 123–137 ms / 3.4 s | 125 ms / 3.9 s |
| Storage | 97 MB | 97.1 MB |
| Relevance (hybrid recall@10 / MRR) | 0.333 / 0.375 | 0.333 / 0.375 |

\*Phase 7 measured structural startup inside the semantic benchmark. No regression. Desktop:
two packaged launches with the fake backend complete in 7.1 s including Playwright startup. Android
performance cannot be measured without a device.

## I. Audits — semantic layer, memory, planner, remote flow

- **Semantic:** the `local` provider embeds in-process; no network. Secrets are detected before
  indexing (`holds_secret`) and such chunks are not stored. Schema changes rebuild the store (§F).
- **Memory:** `coding_memory` admits only durable, confident, secret-free entries; `task_audit`
  refuses secret-named keys anywhere in a record.
- **Planner:** produces plans and roadmaps only; execution still goes through approval.
- **Remote flow:** the push re-verifies a fingerprint of repository, remote, branches and commits,
  validates the SHA, pushes fast-forward only and verifies the remote ref. `--force`,
  `--force-with-lease`, `--mirror`, `--all` and `--tags` are refused. GitHub calls go only to
  `api.github.com` through `github_adapter.py`.
- **Review item:** the approved push uses `git push --no-verify` (documented in Phase 6), so local
  pre-push hooks do not run. Intentional; listed for maintainer review, unchanged here.

## J. Security review

- `shell=True`, `os.system`, `eval`: none in the coding engine. `subprocess` only through the
  hardened MEU runners; `mkstemp` in `cache.py` is an atomic write.
- Git mutations: `commit` (worktree), `cherry-pick` (integration worktree, abort on conflict),
  `push` (approved, fast-forward only). Force flags appear only in deny policy and docs.
- Fixed this phase: retired Nous credentials are blocked from every child environment with no
  exception path (§K, "Legacy key blocking").
- Fixed this phase: the desktop first-run installer always fetches its script from the Meu
  repository; it previously fell back to `NousResearch/hermes-agent` when `MEU_AGENT_MODE` was
  unset.

## K. Dead-code cleanup and Nous removal

Conservative cleanup, plus the requested removal of Nous-specific leftovers (7,436 → 5,753
references; most of the remainder is docs, comments and stale tests).

Removed or made generic: `nous` in every provider, credential, OAuth-grant, sanitization, routing,
pricing and vision list; the dead free-tier error flow (backend branch, 7 error codes, 8 locales);
`is_nous` on the billing wire and `NEEDS_NOUS_AUTH` (contracts regenerated); the "managed Nous →
FAL" mapping that would have billed another account; Nous banner, login brand, TUI tagline and
installer banner; Nous theme and accent ids (renamed to `meu` / `blue`, old stored picks keep
working); `SOUL.md` seed identity; the machine marker now written under `%LOCALAPPDATA%\Meu`
(the old folder is still read); IMAP ID vendor; OpenRouter attribution; electron-builder
maintainer; updater proxy host; user-facing Nous URLs; `docker_rebootstrap_nous_session.py`, the
Nous routing block in `docker/stage2-hook.sh`, the `hermes-nous-prices` catalog entry and their tests.
Legacy config values naming the retired service map to one sentinel, `retired-managed`, and fail
closed with "the retired managed service has been removed; select your own provider".

**Legacy key blocking (not provider support).** `NOUS_API_KEY`, `NOUS_PORTAL_BASE_URL`,
`NOUS_INFERENCE_BASE_URL` and `HERMES_PORTAL_BASE_URL` appear in exactly one runtime place:
`RETIRED_CREDENTIAL_ENV` in `tools/environments/local_env_policy.py`. No code reads them and no
provider registers them. `strip_retired_credentials` removes them, case-folded, as the last step of
every child-environment builder (`hermes_subprocess_env`, the terminal/execute_code sanitizer,
`build_subprocess_env` with or without scrubbing, `served_profile_child_env`), so neither
`inherit_credentials=True`, `env_passthrough`, caller extras nor a profile overlay can pass one to
a child. Before the strict audit the key still reached children under `inherit_credentials=True`
and via passthrough; `tests/tools/test_retired_credential_block.py` now pins all of these paths.

Strict audit (second pass) also removed: the dead `--portal-url` / `--inference-url` flags of
`hermes auth add`; Nous fields in `status`, the turn retry state and the agent cache; the
Nous-only sale/plan branches of `fetch_models_with_pricing`; the Nous auth-lock message; Nous
wording in `gateway enroll`, dashboard help, MCP/plugin catalog text, skills hub, tool notices,
security advisory text and plugin descriptions; the dashboard theme `nous-blue` (now `blue-cream`,
old id aliased); "Nous Research" as the web dashboard footer organisation; and
`LegalCopyright` of the Meu `Meu.exe` (now "Meu Agent"). It also fixed a regression from the first
pass: the stored skin `nous-alt` mapped to itself instead of `meu-alt`.

Final cleanup pass (third): the container backends (docker/modal/daytona) no longer default to
`nousresearch/hermes-sandbox:desktop`; `DEFAULT_SANDBOX_IMAGE` is empty and those backends fail
closed with a clear reason until the user names an image (`tests/tools/test_sandbox_image_required.py`);
migration 48 no longer drops a saved image. `docker-compose.windows.yml` builds the local `meu-agent`
image (`pull_policy: never`) instead of pulling `nousresearch/hermes-agent`. The packaged UIs ship
Meu art only: `apple-touch-icon.png` (desktop window-icon fallback) and the web dashboard favicon
are written by `build-meu-icons.py --derive`; the unused `nous-girl*.png` were removed and the
upstream icon pipeline no longer writes these files. The bundled `hermes-agent` skill (read by the
agent at run time) lost its Nous Portal reference, `/subscription`, `/topup`, `hermes portal` and the
`nous` provider row. Docs: the Nous Portal / Hermes Cloud pages (EN + zh-Hans) and the upstream
translated READMEs were removed, 220 Portal-promotion blocks were taken out section by section, and
`SECURITY.md` now routes reports to the Meu repository's advisories. Catalog entries `billing`
(Nous Portal widget) and `meeting-overlay` (sends transcripts to Nous inference) were removed.
Tests: 115 obsolete Nous-behaviour tests and 5 Nous-only test files were removed (all failing on the
base commit), 217 previously uncollectable tests in `test_auxiliary_client.py` run again (all pass),
and incidental `nous` fixtures were renamed to `provider-a` in 190 Python and 54 TS test files; 22
files where the name carries meaning (legacy-selection refusal, the blocked key) keep it.

Kept, with reason: LICENSE notices (MIT); `meu_privacy.py` and other legacy migrations; legacy
`nous:` session-row handling; third-party model ids (`NousResearch/Hermes-4-70B`); the
`com.nousresearch.hermes` plugin-manifest namespace (compatibility); the `misaki` dependency fork;
the `@nous-research/ui` design-system package (bundled, no network). Not yet done: the
default sandbox image `nousresearch/hermes-sandbox:desktop` (pulled from Docker Hub only when a
container backend is chosen — no Meu image exists); macOS/Linux bundle ids and the upstream
store/light identities (not built for Meu); the macOS DMG background; internal CSS names; ~400
comments; website docs; `.github`.

## L. Dependencies and licenses

No dependency was added in Phases 1–8. NumPy is optional and used only when already installed.
Aider was a conceptual reference only (documented in Phase 1); no code was copied. MIT notices are
retained.

## M. Log and audit secret check

279 log, JSONL, JSON and text files under the test `HERMES_HOME` (`D:\meu-work-data`) were scanned
for OpenAI/OpenRouter-style keys, GitHub tokens, Bearer tokens, AWS keys and private-key headers:
none found. The migration test asserts a fake key never reaches logs.

## N. Crash recovery and soak

- Recovery: `test_task_recovery` and the migration tests pass. Interrupted tasks restore without
  auto-resuming; remote history never re-pushes.
- Soak: 30 cycles of start → approve → reject, 50 refreshes, 10 roadmaps. Median cycle 9.2 s (the
  first took 245 s while a fresh home provisioned its runtime); Python memory +1.3 MB; 1 thread;
  stable handles; no child processes, leftover worktrees, duplicate records or held locks.

## O. Full test results

| Suite | Result |
|---|---|
| Desktop Vitest, full, CI-equivalent | 16,296 passed; failures down to the 2 in §B after fixes |
| Python core (46 files) | 416 passed, 1 skipped |
| Python regression + touched areas (81 files) | 1,339 passed; 6 failures: `test_backup_preflight` (also fails on the base commit), 5 × `test_install_state` symlink cases (WinError 1314, host privilege) |
| Python, 384 files that mention Nous | No failure introduced (compared with the base commit in a detached worktree); ~311 failures pre-exist there, mostly stale tests for code removed in earlier phases |
| ui-tui (affected) | 116 / 116 |
| Typecheck | Clean (renderer, electron, e2e, builder config) |
| Build | `npm run pack` rc=0 |
| Prettier | Clean on every touched file except two that were not Prettier-clean on the base commit either (`overlay-gaps.json`, generated `gateway-contract.openrpc.json`) |
| `scripts/check` | 14 / 14 |

## P. Release checklist

- [x] Desktop, Python and TUI suites green except documented host/base-commit failures
- [x] Typecheck, build, `scripts/check`
- [x] Prompt surface reviewed; docs drift closed
- [x] Packaged isolated launch, update channel and forged-release rejection
- [x] No Nous domains or brand strings in the packaged app
- [x] Logs and audit records free of secrets
- [x] Migrations from Phases 4–7 verified
- [x] Performance not regressed
- [ ] Commit the Phase 8 tree (awaiting approval)
- [ ] CI `verify_upgrade=true` on a disposable Windows runner (real NSIS upgrade and rollback)
- [ ] Signed release build through the release lane (`prepare-meu-release.mjs` requires a clean tree)
- [ ] Android install and pairing on a real device
- [ ] Decision on the sandbox container image (§K)

## Q. Known issues, deferred work and Go/No-Go

Known issues: the two host-only desktop failures (§B); pre-existing ESLint errors in 34 untouched
files; ~311 stale Python tests on the base commit (many target removed Nous code); `git push
--no-verify` in the approved push (§I); OS-locale relative times in the UI (upstream design).
Deferred work stays in `docs/MEU_DEFERRED_WORK.md`.

**GO** for internal RC1 developer validation. **NO-GO** for public distribution until the four
unchecked release items in §P that depend on CI, signing and hardware are complete.
