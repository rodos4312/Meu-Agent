# Meu Windows and Android experience roadmap

Updated: 2026-11-07. Work stays on `dev/meu-foundation`; releases are grouped
after verification. The installed applications are not changed by source edits.

## Verified starting point

- Windows: published dev.25; source starting at `2e62ec212cef`.
- Android: GitHub's 9671 overlay is incomplete when applied to its 9654 ZIP.
  The separately saved Library source identifies itself as **9673** and includes
  the missing web module, the opt-in background service and newer sync code.
  Its SHA-256 is `18ffe27e872f362d4ede1e8e644f0c57d19528f7a70a612d2bcde7aa9c3bf957`.
  It differs from the older complete-source checksum in the 9671 handoff.
- Android package remains `io.github.rodos4312.meumobile.preview`. Existing
  connection IDs, preferences, credentials and protocol names remain compatible.

## Ordered milestones

| Order | Work | Completion evidence |
| --- | --- | --- |
| 1 — implemented and source-verified | Consistent Meu identity and navigation in Windows and Android; clearly distinguish Android execution, PC control and history sync. Show unknown, reconnecting, offline and sign-in states honestly. | Windows Electron navigation rehearsal, translated UI, narrow-screen/text-scaling checks and light/dark Flutter renders passed. Product defaults use Meu assets; custom titles, stored identifiers and legal attribution survive. Physical Android acceptance remains part of final release validation. |
| 2 — source verified | Project workspace: recent projects, accessible storage location, deliverables and useful file previews; preserve drafts and edits when changing views. | First slice: direct project location/copy on both clients, local-only Explorer action on Windows. Android project/file suites passed, including existing write and read-only behavior. Unified deliverables and previews are source-verified; actual phone project/export acceptance remains pending. |
| 3 — source verified | Coordinator visibility on both clients: task, helper, model, acceptance criterion, current state, review result and deliverable. | Native execution remains authoritative. A finished helper awaiting review must not appear verified. Reload/reconnect preserves the same project and run, without spawning another agent. Shared native receipts now extend Windows chat/workspace and Android message projections. See COORDINATOR_VISIBILITY_VALIDATION.md; physical-device acceptance remains pending. |
| 4 — continuity source verified | Continuity and practical mobile work: reconnect to the original run, restore drafts, show pending/conflicted sync items and supported tools. | Disconnect mid-response, reopen, change profiles and reconcile admissions. Exactly one submitted message and one canonical run. History sync does not migrate execution or project files. Preserve the newer 9673 background and conflict handling. See CONTINUITY_VALIDATION.md for the selected-owner fixes, real desktop disconnect/reopen rehearsal and Android cold-start/draft/outbox checks. Physical-device transitions remain pending. |
| 5 — automated checks verified; device acceptance pending | Consolidated stability and privacy checks after the UI/functionality batch. Fix regressions found earlier as they appear. | Windows install/update recovery, Android runtime/background lifecycle, profile isolation, revoked pairing, provider-locked routing, no outbound Nous telemetry. Real Android background/screen-lock and actual Windows reboot checks remain distinct from unit tests. |
| 6 | One consolidated release, with screenshots and accurate release notes. | Matching installer/APK built from recorded sources; checks and device rehearsals reported separately. Do not publish an untested APK or label the whole roadmap complete because unit tests passed. |

## Hermes WebUI ideas, adapted to Meu

Reference reviewed: [nesquena/hermes-webui](https://github.com/nesquena/hermes-webui),
including `f328d3f8e17f92a72fd71cc05f1e45665f2bc662`.

- Explain session ownership and execution location. Browsing a transcript does
  not grant control of another runtime. A connected transport is not proof of
  synchronized history or successful tool execution.
- Keep unknown/loading separate from zero/offline, and running separate from
  completed-but-awaiting-delivery or awaiting-review.
- Retain drafts and attachments after a failed submission, scoped to their
  original conversation and profile; reconcile before resending.
- Reuse project browsing, artifact previews and existing native delegation.
  Meu already has substantial versions of these features.
- Do not import another in-process agent or Linux-only session helper into the
  Windows owner path. Use Meu's canonical backend and existing transport.

## First implementation batch

- Windows pairing now offers explicit PC control/history-sync choices, explains
  which device runs tools, distinguishes a single-history pairing from PC access
  and offers a read-only status retry after a failed poll.
- Android Home gains a device-execution panel. It uses the saved route and
  existing health/auth/socket state, without creating another runtime.
- Android translated product names and inherited header titles migrate to Meu.
  Custom user titles, URLs, commands, identifiers and license credits survive.
- Android source reconciliation retains the newer 9673 code. No APK or Windows
  release is issued for this first batch.

See `EXPERIENCE_VALIDATION.md` for actual check results and limits.

## Deliverables implementation batch

The Windows recent-session catalog and Android current-session browser now
combine generated documents and delivered files, with search, scoped previews,
Save/Download and source navigation. Existing filesystem and viewer authorities
are reused. Windows drive/UNC deliveries and profile/session download routing
are covered by Android tests. See `DELIVERABLES_VALIDATION.md` for checks and
unsupported-format limits. Continue with Coordinator progress/receipts before
the consolidated stability and release checks; no distribution is issued here.

## Coordinator implementation batch

Native progress, acceptance criteria, exact-attempt review receipts and recorded checks now appear on both clients. Windows history restores cards for single deferred-tool calls. Local checks and remaining acceptance are recorded in [Coordinator validation](COORDINATOR_VISIBILITY_VALIDATION.md). Continue with milestone 4 continuity before the grouped stability and release checks.

## Continuity implementation batch

Selected-owner reconnect isolation and Android remote-PC cold-start restoration are corrected. The existing canonical session, durable admission, drafts and encrypted outbox remain the authorities. See [continuity validation](CONTINUITY_VALIDATION.md). Continue with consolidated stability and final device acceptance; release publication stays grouped at the end.

## Stability implementation batch

Cancelled Windows health/status probes and Android runtime startup continuations now retire with their owning attempt. Retry timers release abort listeners. Startup/update recovery, privacy, provider routing and Android background/session suites passed locally; see [stability validation](STABILITY_VALIDATION.md). Physical Android lifecycle and actual Windows reboot/final installer acceptance remain pending. No distribution is published.
