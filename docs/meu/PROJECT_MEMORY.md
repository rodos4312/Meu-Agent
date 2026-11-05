# Project memory

Meu keeps durable project decisions and conventions separately from global agent notes
and the user profile. This extends the existing `memory` tool with `target: project`.
It does not add another model call or require an API key.

Select the project's folder before starting a conversation. Notes saved for that workspace
load into the next conversation using it. The current conversation keeps its original
memory snapshot, including after a correction or an operator rollback. Context compression
retains the existing policy for rebuilding the prompt.

## Scope and storage

- Notes remain in the active profile, under `memories/projects/<folder-key>/PROJECT.md`.
  Successful writes return the local file path. History lives beside the file.
- Registered projects use their primary folder, so their other registered folders share
  the same notes. Otherwise, subdirectories of a Git repository use its nearest Git root.
  Other workspaces use the selected directory itself.
- An ordinary conversation with no selected workspace cannot write project memory.
  The tool reports this and does not substitute global notes. General preferences still
  belong in `target: user`; facts relevant to every project belong in `target: memory`.
- Project notes follow the existing agent-notes enable/disable setting and character
  budget. Existing write approval settings remain unchanged.
- Project notes are not mirrored through the external memory-provider write callback.
  As part of the conversation context, recalled notes are processed by the selected LLM.

The scope is fixed for the conversation. Start a new conversation after selecting a
different folder. A folder rename, move, change of primary folder, or registration with
a different primary folder changes its identity. Old notes remain on disk; automatic
migration of these identities is not implemented. Selecting a broad parent folder does
not infer separate projects from task titles or newly created child folders.

## Inspect and restore

In Desktop, enter a project in the sidebar and choose **Project notes**. The panel
shows stored facts and the local storage path, with Add, Edit and Delete actions.
On a local connection, **Open notes folder** reveals the notes file in Explorer.
Remote paths remain visible without offering to open them on the wrong machine.
An older backend shows an update-required message rather than an empty memory.

Each explicit operator edit goes through the same transactional memory store,
character budget, content checks and version history. It uses the revision read by
the panel. A concurrent agent/operator change refuses a stale save; it never
silently overwrites the newer notes. The panel keeps the draft until the user
reloads or cancels. Agent write approval defaults are unchanged.

In a conversation with an active project store, the existing memory command supports
these explicit project operations:

```text
/memory show project
/memory history project
/memory diff project <version-id>
/memory restore project <version-id>
```

Without `project`, these commands continue to inspect global notes and user preferences.
Pending project writes are bound to the originating project and profile. They cannot be
approved against another project's memory. Restore keeps the active prompt unchanged.

## Verification

`tests/tools/test_project_memory.py` exercises real local files and the production memory
handler, startup prompt injection and inline dispatcher. It covers a fresh Python process,
correction/rollback, project and profile isolation, Git subdirectories, registered folders,
concurrent writes, absent workspaces, pending-write scope and local-only write callbacks.
These automated checks do not establish the quality of an LLM's choice of which facts to save.

## Coordinator handoff

`coordinate_project` returns safe current project facts as `memory_notes`, each
with a content-derived id. For `run`, the parent can supply `task_memory` mapping
the next batch's task ids to relevant note ids. The parent uses the meaning of
the assignment to select notes; there is no extra classification request. An
empty list selects none. An omitted selection retains the task's previous ids
for a retry. Without a prior selection, a helper receives no project notes.

Only those notes enter that helper's initial context. They are background data,
not instructions. The checkpoint records the exact `memory_used` for the attempt.
Changed, removed or blocked notes refuse dispatch before any helper starts; read
status and select the current note ids. The owning parent's database determines
the profile even when an off-turn callback has a different ambient home.

The native project rehearsal now combines note selection, actual file-tool work,
a forced process exit, an operator correction, and continuation in another Python
process. It verifies persisted progress, current relevant notes, helper model
routes and final artifacts. LLM responses are scripted locally; this checks the
runtime and recovery, not a live model's reasoning quality.
