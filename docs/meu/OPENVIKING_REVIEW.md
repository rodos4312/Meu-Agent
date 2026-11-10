# OpenViking review for Meu — 2026-11-10

Research only. No installation, service, new dependency, memory migration,
provider change or data export was performed. The existing optional catalog
entry is not evidence of an installed or enabled memory provider.

Reviewed upstream snapshot: `7be89c23d21c438ce39aadf8d7939ef6f56a4b74`.
Meu's existing catalog pins `e855796c83f9eb575d9b0f3082926660730f6a63`
(plugin 2.1.2); the inspected upstream plugin declares 2.1.4. Its pin was not
changed as part of this stability batch.

## Useful ideas and existing Meu behavior

| Idea | Existing Meu | Decision |
| --- | --- | --- |
| Directory-scoped knowledge, then abstract → overview → details | Project-scoped local notes and explicit per-helper note selection exist; there is no new indexed document database in this batch. | Evaluate bounded project-document summaries later, with source/revision receipts and on-demand detail. |
| Inspectable recalled knowledge | The project memory panel supports versioned edits, stale-write refusal and restore. Coordinator checkpoints record the selected notes per attempt. | Reuse these records for clearer retrieval evidence; do not add a second memory authority. |
| Exact identity for memory edits and deletions | Project/profile scopes and revision checks already prevent applying a stale update to another project. | Preserve exact identity; never infer a destructive target from semantic similarity. |
| Capture and recall separate from conversation history | Meu already separates observed live progress, settled history and execution ownership. | Keep a knowledge service out of the chat/file handoff protocol. It cannot solve missing project files or grant a second executor. |

The upstream virtual filesystem and tiered retrieval are described in its
[README](https://github.com/volcengine/OpenViking/blob/7be89c23d21c438ce39aadf8d7939ef6f56a4b74/README.md).
The exact-target mirroring implementation maintains a profile registry and
serial worker, rather than deleting a similar-looking memory:
[native memory mirror](https://github.com/volcengine/OpenViking/blob/7be89c23d21c438ce39aadf8d7939ef6f56a4b74/examples/hermes-plugin/native_memory_mirror.py).
Meu's current notes and helper-selection contract are documented in
[project memory](PROJECT_MEMORY.md).

## Installation and privacy cost

The plugin can connect to a user-managed service or prepare its own local
service. Its documented Quick Local setup downloads an embedding model of
about 46 MB and more than 1 GB of additional packages per profile. It also
uses configured model credentials for extraction; local storage alone does
not mean that extraction remains on-device. The plugin documents sending
conversation turns, tool results and native memory edits to the selected
OpenViking endpoint. These are reasons to keep installation explicitly
optional, especially on Android. See the
[plugin documentation](https://github.com/volcengine/OpenViking/blob/7be89c23d21c438ce39aadf8d7939ef6f56a4b74/examples/hermes-plugin/README.md)
and [configuration](https://github.com/volcengine/OpenViking/blob/7be89c23d21c438ce39aadf8d7939ef6f56a4b74/examples/hermes-plugin/CONFIGURATION.md).

The inspected server configuration defaults its remote event reporting,
usage reporter and OpenTelemetry exporters to disabled. Its local SQLite
usage/audit projection is enabled. This is a source-level configuration
observation, not a network-capture audit or a guarantee about every deployment:
[server configuration](https://github.com/volcengine/OpenViking/blob/7be89c23d21c438ce39aadf8d7939ef6f56a4b74/openviking/server/config.py).
No such service was started on the owner's computer.

The main project declares AGPL-3.0; its Hermes plugin has a separate MIT
license. No upstream implementation was copied into Meu during this review:
[main license](https://github.com/volcengine/OpenViking/blob/7be89c23d21c438ce39aadf8d7939ef6f56a4b74/LICENSE),
[plugin license](https://github.com/volcengine/OpenViking/blob/7be89c23d21c438ce39aadf8d7939ef6f56a4b74/examples/hermes-plugin/LICENSE).

## Next evaluation, after the stability trial

Use disposable project fixtures to compare relevance, source attribution,
retrieval latency, prompt-prefix stability and actual model token usage.
Include stale summaries, edited/deleted source files, cross-project/user
isolation and an unavailable knowledge service. Recall failure must not stop
the autonomous Android agent. Measure native Windows and Android resource
cost before considering any package addition. Upstream benchmark gains are
not measured Meu savings.
