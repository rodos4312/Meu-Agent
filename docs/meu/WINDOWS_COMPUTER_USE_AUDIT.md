# Meu Windows Computer Use — Source Audit 01

Status: static source review only. **Not** a Windows runtime benchmark, implementation or certification.
Target: Windows 11 native (no WSL, no Docker), isolated Meu profile.

## Actual call path

1. `apps/desktop/src/app/settings/computer-use-panel.tsx`: readiness view calls `getComputerUseStatus()` and shows the Windows driver guidance. On Windows, there are no macOS-style TCC buttons.
2. `tools/computer_use/permissions.py::computer_use_status`: resolves `cua-driver` and runs `doctor --json`; on Windows, `ready` follows driver health.
3. `tools/computer_use/tool.py::handle_computer_use`: agent tool dispatch, per-session backend, action gating, capture deduplication and delivery-mode validation.
4. `tools/computer_use/cua_backend.py`: `cua-driver` stdio MCP bridge; platform-specific actions live in `cua_backend_input.py`, `cua_backend_capture.py` and `cua_backend_session.py`.
5. `tools/computer_use/backend.py`: normalized results include delivery path, `verified`, `effect` and optional escalation advice. `ok` alone does NOT prove a click changed the UI.
6. `tools/approval.py` + `tools/computer_use/tool.py`: shared per-session approval and grant store.

## Findings relevant to the previous manual test

**F1 — Native Windows is supported by code, not yet validated on the user's host.**
The desktop status panel and `permissions.py` expressly handle `win32`. Driver readiness, actual UIAccess worker availability, session boundary and desktop permission must be checked at runtime. A passing `doctor` is necessary but does not prove mouse/keyboard actions complete correctly.

**F2 — The approval problem is a policy/grant-scoping question, not proof that confirmation prompts can simply be disabled.**
`tests/tools/test_computer_use_approval_isolation.py` demonstrates that a computer-use grant uses a shared key such as `cua:click:background`; an `always` grant can suppress the next same-key prompt in the same session. Whether the previous user's UI granted that exact action/mode/session is not yet known. DO NOT select `--yolo` as a workaround: `tool.py::_cua_permission_mode` deliberately escalates the driver's permission mode to `unrestricted` for bypass sessions.

**F3 — Some latency work already exists upstream.**
`cua_backend.py::_cua_configured_ax_max_elements` defaults to 200 driver-side AX elements; the source documents *macOS* measurements, **not Windows measurements**. `tool.py` deduplicates consecutive identical captures for a session (max omission streak 2). Consequently a generic “add screenshot caching” patch could duplicate existing behavior or compromise freshness.

**F4 — Safe success means effect verified.**
The backend distinguishes transport success (`ok`) from observable effect (`verified`, `effect`). A Meu UI should show and audit this distinction and stop/escalate carefully on `suspected_noop` rather than hallucinate success.

## Baseline to collect on a real Windows 11 test machine (not run yet)

Run in **PowerShell** after selecting a disposable, non-privileged test application and isolated Meu profile:

```powershell
hermes computer-use status
hermes computer-use doctor
hermes computer-use permissions status
```

Record the diagnostic output, redacting usernames, paths and any credentials before sharing. For the UI benchmark, record per-step elapsed time (capture, click, type, verification), active target/window, requested delivery mode, actual delivery path, reported `verified/effect`, and prompt count. Run 5 repetitions after warmup for each action, report median and slowest result. The Windows machine's installed `cua-driver` version must also be recorded.

## Decision before coding

- Do **not** replace the backend or disable approvals based on anecdotal slowness.
- First establish whether the bottleneck is driver capture/AX, backend lifecycle, provider model round-trips, or prompt handling.
- Build the first patch only after the result is reproducible with one failing test. Preserve the existing upstream tests (`test_computer_use_native_platform.py`, `test_computer_use_approval_isolation.py`, `test_cua_perf_knobs.py`).
- Prefer a Meu plugin/config layer; core changes require proof that an extension cannot solve the issue.
