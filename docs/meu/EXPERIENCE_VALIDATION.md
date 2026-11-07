# Experience batch validation — 2026-11-07

This records source-level validation for the first batch in
[the experience roadmap](EXPERIENCE_ROADMAP.md). It is not a release receipt.

| Check | Result |
| --- | --- |
| Windows pairing UI | **10 passed** using native Windows Node/Vitest. Covers explicit mode routing, scoped session selection, single-history pairing, legacy profile flags, zero listeners, missing expiry, last contact and recovery after a failed status read. |
| Windows static checks | Desktop TypeScript renderer, Electron and E2E typechecks passed. Targeted ESLint passed with zero warnings; translation key inventory regenerated; `git diff --check` passed. |
| Android Flutter | **27 passed** across execution-panel, custom-title persistence, Home authentication, profile sync stability, opt-in background controls, local runtime, web tools and license preservation suites. |
| Android branding helper | **2 passed**: preserve URLs, commands, interpolation and protocol identifiers; applying the transformation twice is safe. |
| Android static checks | Changed screens, execution panel and new widget tests analyzed without issues. All nine ARB catalogs regenerated successfully. |
| Android native resources | Android SDK 36 `aapt2 compile` accepted the Meu resource overrides, including localized notification branding. |

## Important cases checked

- A 320-pixel-wide display with 1.8× text scaling has no overflow in the new
  execution panel. The existing Home-header narrow-screen test also passes.
- A loopback address without an explicitly on-device route does not become a
  claim that the phone owns execution. Losing contact retains the selected
  device while displaying unavailable/reconnecting, rather than connected.
- A read-only route is identified independently from its connection state.
- An inherited Console header migrates to Meu; a custom user title survives
  save/reload, and startup does not silently rewrite the saved preference.
- History pairing is not shown as control of the PC agent. Zero listeners are
  not shown as a ready sync service. A status retry performs reads only.
- Existing sync tests retain conflict handling and cancellation fencing.
  Existing runtime tests retain authenticated local sign-in and stop behavior.
- GPL and MIT attribution is still registered and tested. Product rebranding
  does not erase license notices or rename stored protocol identifiers.

## Reproduce

From the Windows repository:

```text
npm exec --workspace apps/desktop -- vitest run --project ui src/app/settings/mobile-preview-panel.test.tsx
npm run typecheck --workspace apps/desktop
```

From the complete Android source:

```text
python scripts/prepare_meu_branding.py
python scripts/test_prepare_meu_branding.py
flutter gen-l10n
flutter test --no-pub --flavor meu --dart-define=MEU_PROOT_EXPERIMENT=true test/about_screen_license_test.dart test/meu_execution_panel_test.dart test/meu_header_branding_test.dart test/home_dashboard_auth_status_test.dart test/meu_profile_sync_stability_test.dart test/meu_agent_background_test.dart test/meu_runtime_screen_test.dart test/mobile_web_test.dart
```

Use an SDK path without spaces, or its Windows short path, when the Flutter
native-assets hook invokes Dart on Windows. Dependencies were resolved from
the existing package cache; no model provider request was needed.

## Still unverified

No physical Android installation, lock-screen/background endurance run, mobile
data transition, live-provider project or real Windows reboot was performed in
this batch. No new APK or Windows installer was built or published. Full app
visual review and the remaining handwritten Android strings/assets belong to
the next part of milestone 1. The remaining milestones are not complete.
