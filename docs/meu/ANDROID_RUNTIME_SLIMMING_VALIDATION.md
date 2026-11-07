# Android runtime slimming and helper cancellation

Source validation, 2026-11-08. Development branch only; no new distribution,
installed-app changes or update-feed promotion.

## Cancellation

Core commit `17c2fa366872f33eece225b1e18c096ee47e6e1f` fixes a helper waiting
behind the process-wide Meu execution semaphore. Previously, stopping that
helper could leave it blocked until another worker released a permit, after
which it could start a model call. Admission now observes cancellation while
waiting and at permit handoff. A cancelled queued helper returns interrupted
with zero API calls, closes once and releases only a permit it acquired.
Existing detached-background ownership and canonical turn-start binding stay
unchanged.

Two soft/hard cancellation regressions failed before the correction and pass
with both other permits still occupied. The historical intermittent CI failure
was investigated separately: its first failure was a five-second pre-start
coordination deadline, followed by workers surviving into later fixtures.
Startup/cleanup orchestration now allows 30 seconds, with all test-owned gates
released before joining workers. The existing five-second checks for receipt
and unwinding after an actual stop remain unchanged. These are distinct fixes;
a clean retry alone was not treated as evidence of correction.

Local Windows evidence:

- 15 capacity/cancellation cases passed in five consecutive fresh runs with
  `--file-retries 0` (15 unique cases, not 75 unique tests).
- Three gate/concurrency files: 20 passed, no retries.
- Seven broader delegation, schema, background and review files: 113 passed,
  two host-specific skips, no retries.
- Required source quality command: 14 checks passed, zero blocking/advisory
  findings.

Exact-source GitHub verification:
[run 42424466823](https://github.com/rodos4312/Meu-Agent/actions/runs/42424466823).
All six required jobs succeeded; three optional distribution jobs were skipped.
The 15 cancellation cases passed on their first attempt on Windows and Linux.
Linux's focused backend batch passed 346 cases with one skip; the Windows
privacy batch passed 1,782 with 30 skips. The subsequent Windows batches passed
395 (11 skips), 18 and 50 cases. Native Windows navigation passed ten cases,
and complete Windows CI dispatch replay passed 101 with one POSIX-only skip.
These overlapping batches are not summed as unique coverage.

One unrelated bootstrap-test flake remains open:
`test_generated_windows_pins_match_the_shared_authority` in
`tests/scripts/test_bootstrap_mirror.py` exceeded its 30-second PowerShell
subprocess deadline on the first attempt, then passed on retry. The workflow's
green conclusion does not close this new follow-up. It is not a cancellation
failure, and no bootstrap correction is claimed by this batch. Earlier green
runs apply only to their own source revisions.

## Android engine contents

The Android preparation helper now creates an offline Git sparse/promisor seed
from that exact core commit. It keeps commit/tree metadata and selected runtime
blobs, while physically excluding frontend and development blobs from the
archive. This is more than skipping their compilation. Original Git identity
is preserved; no parallel engine or updater is introduced.

| Inventory | Count |
| --- | ---: |
| Included runtime source files | 5,179 |
| Excluded files | 16,638 |
| Selected runtime source bytes | 78,717,288 |
| Full tracked source bytes | 235,187,416 |
| Compressed seed bytes | 29,066,591 |

Excluded roots include `apps/`, `web/`, `ui-tui/`, `tests/`, `website/` and
`.github/`, plus the frontend root package manifest. Backend Python, shared
gateway modules, tools, skills, plugin support and memory remain. Names of
excluded paths can still occur in Git tree metadata; their unique source
content blobs are absent. Explicit future Git operations could fetch missing
objects; normal restore/reset was verified without network access.

`runtime.properties` replaces three duplicated engine pins. Native startup and
the guest use its revision; Meu asset merge validates the matching seed and
installer hashes. Generated binary seed and installer assets are ignored and
must be regenerated from the locally available reviewed commit before building.
The guest always uses the canonical `--backend-only` path from this new engine.

Seed SHA-256:
`5951843d98857e7fe7cffe5483a955704a6af53547eae0cd581720bebd4249dd`.

Installer SHA-256:
`97abad73e18f084c1d009455a6b7a61b15a46c580ce2c52a9dea7e5e479f79a6`.

A real Bash subprocess test also caught a missing checksum export between the
guest and injected installer function. It failed before `seed_sha` was exported
and passes after the correction. It restores a fixture seed using the actual
guest function with Git network protocols denied.

## Validation and preserved web capability

- Four Python tests passed: fixture seed generation/restore, exact object
  selection, reproducibility in the same toolchain, subprocess handoff and
  provider configuration/persistence.
- The actual full-size lean seed restored offline with original commit identity
  and no frontend directories. Seven real backend/tool modules imported from
  that restored source with network access refused; canonical `serve` argument
  parsing passed. This is an import/parser smoke check, not a running Android
  backend or an Ubuntu installation receipt.
- Eighteen focused Flutter tests passed across mobile-web policy, runtime UI,
  background ownership, install progress and OpenRouter configuration.
- `:app:validateMeuRuntimeAssets` and `:app:compileMeuDebugKotlin` passed offline.
  Guest and preparation wrapper passed Bash syntax validation.

The native Android viewer remains; removing the browser-dashboard source does
not remove web reading. The retained core includes `tools.web_tools`, plus
optional DDGS setup in the guest. HTTP reading/search, user-facing WebView
preview and full interactive browser automation are separate capabilities.
JavaScript/login/click automation has not been certified on a physical phone.

Private source backup: `Meu-Mobile-private`, branch `dev/meu-foundation`, commit
`9b3ba72`. The archive contains 2,710 allowlisted files, individually hash-checked
against working source. Archive SHA-256:
`0d9150ce0a19e9ae213d44d36bdc04d15c620d34f1bda6805c3ed09f0c0af09f`.
Keys, local settings, build caches, generated runtime binaries and APKs are
excluded. Prior snapshots retain their own historical check receipts.

## Remaining acceptance

Investigate the Windows PowerShell bootstrap-test timeout above before treating
the required CI run as free from intermittent test failures.

No final APK-size or first-install-speed claim follows from the source byte
reduction. Real-phone PRoot installation/startup, web requests, model calls,
project creation, previews/Save, screen lock/background, mobile-data and paired
PC continuity still need candidate acceptance. Windows OS-reboot recovery stays
explicitly deferred. Matching final packages and a consolidated release remain
at the end; this batch creates neither an APK nor a release.
