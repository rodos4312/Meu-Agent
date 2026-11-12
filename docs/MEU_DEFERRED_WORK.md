# MEU deferred work register

Versioned list of work that is known and intentionally deferred. The Meu Coding Engine's
Autonomous Planner reads every `- [CATEGORY] …` line below as project knowledge, so a roadmap
does not pull these items into unrelated work. Edit this file like any other source file.

- [DEFERRED_WORK] 97 known pre-existing desktop full-suite test failures (43 Vitest files / 94 tests stable, plus electron/plugin-files-spellings.test.ts, which fails only under full-suite load) are deferred to the final cleanup/hardening phase (Phase 8); do not fix them in unrelated tasks.
- [DEFERRED_WORK] Android real-device validation of the legacy Java companion (install, launch, coding and remote approvals) is pending until a device or emulator is available.
- [DEFERRED_WORK] The GitHub REST client of the remote workflow has not been exercised against github.com; validate on an isolated repository before real use.
- [KNOWN_LIMITATION] The REMOTE section of the desktop Coding page has not passed a live Electron smoke test.
- [DEFERRED_WORK] Coding Engine Phase 7: a neural embedding provider and a test against a real API embedding endpoint are still pending (only the local lexical embedder was benchmarked).
- [DEFERRED_WORK] Coding Engine Phase 7: the Android roadmap UI and a live Electron smoke test of the Phase 7 desktop sections are still pending.
