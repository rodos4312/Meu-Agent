# Experience batch validation — 2026-11-07

This records source-level validation for the first batch in
[the experience roadmap](EXPERIENCE_ROADMAP.md). It is not a release receipt.

## Completed navigation and first project-location slice

The follow-up on the same date finished the navigation implementation and
started milestone 2 without changing either application's published version.

- **Windows:** 46 focused UI/integration tests cover navigation, capability
  selection, the welcome screen, project locations and existing project/session
  drag behavior. A real Electron navigation rehearsal against an isolated local
  Python backend passed, including draft retention, Connectors/Tools selection,
  1024/640/400-pixel widths, Settings at 400×320, light/dark appearance, a mock
  provider conversation and return to the same transcript. No renderer Nous
  requests, shared-metrics RPCs or metrics-storage keys were observed.
  A separate Electron rehearsal created a real temporary project, displayed
  its location, edited its note file, restarted the test app and verified the
  persisted note. Both E2E scenarios passed; the user's installed app was not
  used or restarted.
- **Android:** **263 tests passed in one final combined run**: navigation,
  onboarding, device switching, auth status, voice/template branding, themes,
  chat back-navigation, projects/tablet detail, file browsing/writes and artifact
  navigation. Two additional Flutter rendering scenarios passed and produced
  Home/drawer screenshots in light and dark mode at 390×844.
- The two Python branding transformation tests from the first batch remain
  applicable. Changes passed targeted Flutter analysis, desktop TypeScript
  checks and targeted ESLint. The Windows production bundle built successfully.
- Product defaults now use Meu images in loading, onboarding and drawer/header
  surfaces, plus Meu labels in avatars, About, themes, voice/browser notices and
  save dialogs. Custom names and user arguments are preserved; license credits,
  model IDs, commands and persisted route/theme keys are not renamed.
- Android's local-start button had retained the QR icon and test/action key;
  these now match its actual action. PC pairing remains optional. Saved PC
  connections and connection management stay accessible in the Android-agent
  variant. Previously handwritten onboarding/menu copy follows all nine UI
  locales. Empty Greek voice notices were filled and registry parity verified.
- Project folders are visible and directly copyable on both clients. Windows
  offers Explorer only for a local execution route. Android copies the full
  host path even on a read-only route, with no file write or path migration.

The screenshots use synthetic data. Flutter-rendered Android screens are not
evidence of a physical-phone installation, background endurance or mobile-data
connectivity. A unified deliverables view and real-device project/export
acceptance remain work for milestone 2. No new installer/APK is distributed.

The private Android source snapshot contains 2,688 files. Every archived file
was checked against its SHA-256 manifest; no input source file was removed.
Archive SHA-256: `c1ca7979020c411e225b237d901084b1d62aa9c5fdcbf88d5be94ab3e1bd3d29`.

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
this batch. No new APK or Windows installer was published. The follow-up above
records the completed navigation slice; it does not certify every screen,
external plugin or the remaining roadmap milestones.
