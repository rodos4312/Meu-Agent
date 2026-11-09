# Meu 0.1.0-dev.28

## Continue on a phone while the PC is closed

Ordinary single-device continuations synchronize when the other device returns;
the PC does not need to remain on. A running, queued or uncertain turn is now
deferred before exporting a partial answer or declaring a destination conflict.
Reads bind authorization, write-guard checks and text to one SQLite snapshot.

If both agents really produced different continuations, Android 9684 offers an
explicit phone/PC continuation choice under the same session ID. Both compared
copies are saved first. The displaced local suffix is soft-archived using the
existing rewind persistence API, including internal/tool rows. Expected-version
checks refuse newer messages and durable receipts make retrying a lost reply
safe. Recovery never submits agent work, tool calls or provider settings.
Warm agents reload the chosen transcript before the next prompt, even when
both copies have the same number of messages. Cache re-baselining cannot
silently acknowledge a recovery that the agent has not loaded.

Android displays only the differing suffixes after the common prefix. Text
backups can be read from its local database with the PC off. Personal pairings
retain their assigned history scope; another named user's backups stay private.
Project files, API keys, pairing credentials and storage paths are unchanged.

Install both this Windows candidate and Android 9684 to use the new recovery
controls. Android 9682 keeps its full runtime and regular synchronization; it
does not gain these controls from a Windows-only update. Genuine simultaneous
offline edits still require a continuation choice; no version is silently
discarded or semantically merged. If one device changes during two-device
recovery, its newer messages remain intact and comparison must be refreshed.

Earlier recovery checks cover 63 backend cases and the Android dialogs, stale-version
refusals, private transport and named-space authorization. The real Python bridge
was also exercised against the older pinned Android engine on the host;
the candidate updates that engine to include warm-history reconciliation.
Native candidate builds, release verification and physical-device acceptance
are separate gates. The owner's already-conflicted chat has not been edited.

## Shared live conversations and unified devices

Connected Windows and Android views use the same canonical PC conversation,
message admission and tool execution. Reconnect replays events or a snapshot;
uncertain sends are not submitted to another engine. The phone remains able to
work autonomously when the PC is unavailable, with explicit execution ownership.

Settings now has one Devices and sharing surface. Existing durable owner
pairings migrate without a new QR, token, TLS identity, port, history ID or file
path. Each additional device has an independent QR and revocation. A device
explicitly marked PC owner keeps the PC workspace; separate named users keep
their own transfer folders and conversation scope. Available Wi-Fi and Tailscale
endpoints are included in the new pairing. Temporary legacy connections remain
compatible until expiry/disconnect, without silent permanent enrolment.

## Coordinator reliability and reusable prompts

Windows checkpoint persistence retries a transient reader hold through the
existing atomic writer. New helpers place shared workspace/rules and capability
guidance before task-specific context. Their goals, acceptance checks, tool
policy and model routing are retained. Local recording-provider checks measured
a longer common system prefix at the same total text size; actual cache billing
is decided by the selected provider and is not measured by that fixture.

## Trial scope

Android 9684 retains the full 9680-style navigation, on-device runtime, Auto,
existing preview package and signing certificate. It adds the later live-chat
client source and refreshes the embedded engine to the reviewed batch revision.
Install over the existing preview without removing its data. Native package
inspection and host integration tests are separate from physical-phone testing.
The final package/version/hash records identify the bytes actually delivered.
