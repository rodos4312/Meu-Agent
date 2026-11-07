# Android providers, installation progress and focused cleanup

Development source only, 2026-11-07, `dev/meu-foundation`. No release, APK,
installer publication, feed promotion or installed-app modification.

## Behavior

Autonomous Android setup now offers DeepSeek and OpenRouter. Each provider has
its own secure key slot. OpenRouter lets the user choose light and strong model
IDs manually or from its public tools-capable model catalog. Discovery uses a
bounded, timed, fixed HTTPS request without an API key, prompt or device ID;
it does not establish account entitlement or free usage.

The general Coordinator uses the selected pair on the active provider. Routine
helpers use light; standard/complex helpers use strong. Vision work stays within
that pair or reports known incompatibility, rather than silently choosing a
third model. This also corrects Windows/shared-core routing. The strong model
initially becomes the Android main default for new chats; helper selection is
not a new automatic main-chat selector. Cold resume preserves later choices.
Busy owners refuse provider/key/model replacement; existing credentials, other
settings and per-conversation routes survive ordinary restart.

Installation reports actual elapsed time, the current stage, recent redacted
output and prolonged silence. Known-size downloads display bytes and percentage;
dependency installation stays indeterminate. Ready status excludes setup logs.
No estimated completion time or whole-install percentage is fabricated.

The canonical `--backend-only` installer mode skips the terminal/browser/desktop
renderer builds unused by the native Android client. It retains the engine,
tools, skills, launchers, source identity and configuration/memory/plugin
maintenance. Normal Windows builds keep their existing default path. Combining
this mode with a Desktop build or leaving an existing built Desktop stale is
refused. The Android guest checks the pinned installer's advertised options
before supplying the flag, retaining compatibility with its older seed.

## What was actually removed

- The 416-line obsolete dashboard-registration test file and its unused serve
  fixtures, left behind after the implementation was removed in `6b7f49284c`.
- The 107-line obsolete anonymous Nous rate-guard test file, five Portal-only
  model-test classes and the removed Nous proxy adapter's tests/helpers.
- One uncalled ANSI usage-gauge formatter and unused imports/fixtures. Generic
  terminal gauge rendering, active catalogs, local model discovery, proxy
  authentication isolation and SSE/security checks remain tested.

A static audit of direct top-level owned-module imports in 7,109 test files
identified four further missing-module references. These were resolved by
retiring Portal-specific tests and preserving active tests in mixed files.
This bounded audit does not establish that every file in the project is used.
Negative tests reject retired modules, CLI commands and the Portal adapter
before any network request. Removing tests improves maintenance, not APK size.

Android also shares provider-environment parsing instead of duplicating a
DeepSeek-only parser. Its project brief now describes autonomous and PC modes
accurately. Two Greek voice style findings were corrected without changing
behavior; existing licenses and attribution remain intact.

## Evidence

| Check | Observed result |
| --- | --- |
| Shared Coordinator explicit-pair dispatch | 49 passed, including six OpenRouter pair/vision cases; failures were reproduced before correction |
| Canonical backend-only builds, completion and Desktop detection | 32 passed, 13 host-specific skips on native Windows |
| Retired registration and active serve/dist paths | 16 passed before extending retired-module coverage |
| Active model catalogs, proxy, terminal gauges and retired-service guards | 101 passed, no file retries |
| Repository quality | 14 checks passed on installer work, and 14 again on the final cleanup; no blocking/advisory health findings |
| Native Bash CI follow-up | Six installer cases passed locally again; scoped health/Ruff checks passed |
| CI graph and release admission | 13 passed after adapting the stale upstream tag invariant to Meu's exact existing release-request namespace |
| Android functional suite | 42 passed, including two light/dark render scenarios at 390x844 |
| Android analysis | Whole production library plus four new test files: no issues |
| Native Android compilation | Offline `:app:compileMeuDebugKotlin` succeeded; no APK assembled |
| Pure native provider and progress/privacy checks | 9 provider checks and 8 progress checks compiled and executed |
| Android bootstrap configuration | 2 Python tests with real temporary YAML writes; no paid inference calls |

The preceding core routing revision `f23661190395` passed all six required
GitHub jobs in [run 42411326557](https://github.com/rodos4312/Meu-Agent/actions/runs/42411326557).
The installer/cleanup source is `51671378c7f40a5d8f94ecf812f50ed3683e467c`
(installer commit `891493537736` followed by test cleanup). Its
[run 42413839639](https://github.com/rodos4312/Meu-Agent/actions/runs/42413839639)
passed 344 Python checks and 1,839 terminal checks on Linux. Windows exposed two
test-harness failures: an unqualified `bash` resolved to the WSL launcher.
The other 1,778 cases in that Windows batch passed; this run was not fully green.

Follow-up `de4441f068958f0dbbeb04192a51f4aa0597e98a` uses the existing native
`real_bash` test fixture and adds regression-only paths to this workflow's push
selection. Follow-up `02f997db0e8edd9941f75e8060427a70b56b92b7` corrects a stale
CI graph assertion: Meu's existing release-request tag namespace and development
branch are explicitly admitted, and the graph check now runs in the installer
lane. These follow-ups change no installed runtime behavior. The exact-head
[run 42414895061](https://github.com/rodos4312/Meu-Agent/actions/runs/42414895061)
completed successfully: all six required jobs passed; the three optional
distribution jobs were skipped. Windows privacy/tool batches passed 1,780
(30 host-specific skips), 395 (11 skips), 18 and 50 cases respectively.
These batches overlap with other lanes and are not summed as unique coverage.
Ten native Windows UI cases passed, including real app restart and restored
Coordinator receipts. Complete Windows CI dispatch replay passed 101 cases
with one POSIX-only skip. The final privacy job reported no flaky file retry;
this does not fix the historical intermittent cancellation failure.

Android source is privately backed up at `93ee426` in `Meu-Mobile-private`,
branch `dev/meu-foundation`: 2,706 allowlisted source files, with every archived
file checked against its working-source SHA-256. ZIP SHA-256:
`e9ef00b0e1ddf2c856a4fa0769f7a9aed347f4ef1cc35561ffac84cd80ad35e8`.
Generated build caches, local configuration, signing keys, API keys and APKs
are excluded. The earlier 725-test receipt remains historical, scoped to the
preceding Android snapshot; it is not claimed as a rerun on these bytes.

## Remaining acceptance

The Android preparation script, native owner and guest still pin engine
`cb43517b6dbd9e9c5c762150c907c2d56c2a1590`. Before the consolidated APK, admit
the updated core and regenerate the matching embedded seed/installer hashes.
Until then the old seed does not contain backend-only optimization or the
latest pair-routing fixes. UI source alone does not update that engine.

Measure first-install duration on a physical phone, then verify real tools,
the exact provider/model pair, persistence after close/reopen, busy-work
protection, and both autonomous and paired-PC modes. Native compilation and
widget tests do not certify physical PRoot, screen lock/OEM background behavior,
mobile-data access or file export. No installation speedup has been measured.

The previously observed intermittent cancellation-suite failure remains open;
its pass on retry is not a fix. Actual Windows OS-reboot recovery stays an
explicitly deferred extended case. Final packages and their acceptance remain
grouped at the end.
