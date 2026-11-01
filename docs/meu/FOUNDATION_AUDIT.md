# Meu Agent — Foundation Audit and Engineering Gates

Status: architecture reconnaissance (not a security certification or successful Windows build).
Base: fork of NousResearch/hermes-agent; development branch `dev/meu-foundation`.
Target: Windows 11 native desktop, Greek-first, personal DeepSeek endpoint, optional Android bridge.

## Verified code map (source: fork at initial main)

| Concern | Existing Hermes seam | Meu strategy |
| --- | --- | --- |
| Agent lifecycle | `run_agent.py`, `agent/conversation_loop.py`, `agent/turn_*.py` | Preserve core loop and prompt-cache invariants. |
| Memory | `agent/memory_manager.py`, `agent/memory_provider.py`, `plugins/memory/` | Evaluate existing persistence, redact-before-egress and cross-session recall before adding a provider. |
| Skills | `agent/skill_utils.py`, `skills/`, `agent/curator*.py` | Introduce proposal/review/approve workflow at the skill mutation boundary; keep original skill and rollback history. |
| Desktop | `apps/desktop/` (Electron/React) | Native Windows-only acceptance tests; avoid a premature rewrite. |
| Gateway | `gateway/` | Keep Android transport behind a versioned adapter; do not expose the local desktop via an unauthenticated public port. |
| Scheduling | `cron/` | Do not activate unattended jobs until permissions and cancellation are tested. |

## Constraints

1. Never commit API keys, Telegram tokens, local chat history or private memory to this public repository.
2. Use an isolated runtime profile and distinct installation/data directory for Meu tests; do not modify the currently working Hermes installation.
3. Default to per-action consent for filesystem, shell, network and desktop control. Time-limited scopes and explicit audit entries are required before broader approvals.
4. No automatic changes to installed skill instructions or high-trust memory. Proposed changes must be inspectable and reversible.
5. Keep upstream changes reviewable. The protected integration flow is: upstream sync -> review -> branch tests -> Meu integration.
6. Do not infer native Windows GUI automation works from shell access; verify actual screen read, mouse/keyboard actions, failures and cancellation on Windows 11.
7. No trading order execution in the foundation stage; any future MT5 integration starts read-only and requires separate authorization.

## Acceptance gates

- **G0: code audit:** trace current desktop computer-use capability and permissions to actual source locations; enumerate security boundaries and regression tests.
- **G1: isolation:** a fresh Meu profile starts without reading or changing the existing Hermes profile, its secrets, or its installed skills.
- **G2: Windows smoke:** launch, chat with configured personal DeepSeek provider, read a screen, interact with a disposable test window, cancel an action, and restart.
- **G3: memory:** demonstrate cross-session recall, a correction, inspectability, versioned rollback, and no key leakage.
- **G4: skills:** unsuccessful tasks cannot silently rewrite active skills; review shows a diff; approval and rollback have tests.
- **G5: Android:** authenticated pairing, key rotation, disconnect, replay/reconnect behaviour, no unauthenticated inbound exposure.
- **G6: release:** signed/reproducible package strategy, clean Windows install and uninstall, upgrade rollback and smoke suite.

## Immediate technical observations

- Hermes describes plugin/skill extension as its preferred path and explicitly treats stable prompts/tool schemas as invariants (`AGENTS.md`).
- The existing memory manager redacts information before sending it to registered external providers (`agent/memory_manager.py`); this is a useful boundary to retain, not proof of comprehensive secret safety.
- Hermes Desktop is a real Electron UI with a Python runtime (`apps/desktop/README.md`), not merely a terminal wrapper.
- Current public fork is an upstream copy. No Meu feature is implemented or verified yet.

## Next implementation step

Inspect `tools/` and desktop Windows computer-use handling plus relevant tests, document a reproducible failure/latency baseline, and implement the smallest behaviour change with a regression test. Do not rename the entire codebase before a working isolated smoke test.
