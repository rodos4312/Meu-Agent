# Meu desktop navigation preview

Version: `0.1.0-dev.3`, on `dev/meu-foundation`.

The desktop has a persistent navigation rail for Home, Scheduled jobs, Plugins,
Skills and Settings. Home returns to the previous chat route. Navigation uses
the existing workspace and overlay actions; it does not create a session or
submit a prompt. The chat composer and session sidebar stay mounted while
another section is visible.

Plugins and Skills open the existing capability managers. Their contextual
sidebar also exposes Connectors and Tools. When that sidebar is hidden, narrow
or embedded in a plugin dialog, the existing top tabs remain available.
Profile and connection scope, plugin installation, skill enablement and MCP
configuration continue through their existing backend APIs. No new approval
gates were added for memory, skills or computer use.

The empty chat uses a compact Meu wordmark and a readable welcome heading.
Personality-specific introductory copy remains intact. New navigation copy
is provided for all nine bundled UI languages.

## Verification

The Windows navigation E2E starts a real Python backend against a local mock
inference server. It checks the resolved product home before interacting,
verifies the mock model, retains an unsent draft across pages and overlays,
checks widths of 1024, 640 and 400 pixels, completes a mock conversation, and
returns to the same transcript. It also changes appearance through Settings.
Screenshots are saved as CI artifacts.

The E2E fixture must set **both `MEU_HOME` and `HERMES_HOME`** to its temporary
home. Meu deliberately ignores inherited Hermes data roots. Before this fixture
correction, the navigation-only rehearsal read an existing Meu backend; that
run is not evidence of isolation. No message was submitted in that rehearsal.

Run from `apps/desktop` after building:

```powershell
$env:HERMES_DESKTOP_PYTHON = (Resolve-Path '../../.venv/Scripts/python.exe').Path
npx playwright test e2e/meu-navigation.spec.ts --reporter=list --workers=1
```

The Meu Windows workflow also retains the privacy/DeepSeek regressions,
navigation and capability unit/integration tests, localization checks,
typechecking, packaging and installer lifecycle tests. A passing navigation
test establishes the covered flows, not every plugin or external service.
