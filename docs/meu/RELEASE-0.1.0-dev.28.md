# Meu 0.1.0-dev.28

## Continue on a phone while the PC is closed

Ordinary single-device continuations synchronize when the other device returns;
the PC does not need to remain on. A running, queued or uncertain turn is now
deferred before exporting a partial answer or declaring a destination conflict.
Reads bind authorization, write-guard checks and text to one SQLite snapshot.

If both agents really produced different continuations, Android 9683 offers an
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

Install both this Windows candidate and Android 9683 to use the new recovery
controls. Android 9682 keeps its full runtime and regular synchronization; it
does not gain these controls from a Windows-only update. Genuine simultaneous
offline edits still require a continuation choice; no version is silently
discarded or semantically merged. If one device changes during two-device
recovery, its newer messages remain intact and comparison must be refreshed.

Local checks cover 63 backend cases and the Android dialogs, stale-version
refusals, private transport and named-space authorization. The real Python bridge
was also exercised against the older pinned Android engine on the host;
the candidate updates that engine to include warm-history reconciliation.
Native candidate builds, release verification and physical-device acceptance
are separate gates. The owner's already-conflicted chat has not been edited.
