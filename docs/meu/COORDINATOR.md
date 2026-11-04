# Meu Coordinator

Available in `0.1.0-dev.4` through **Settings → Model → Subagents → Meu Coordinator**.
The choice is profile-scoped and persisted through the existing delegation API.
It applies to new sessions; a running session retains its original tools and prompt.
Existing routes are not silently overwritten. The updated Python backend must contain
the bundled `plugins/delegation/meu_coordinator` plugin; replacing the desktop executable
alone does not update an older backend installation.

The parent LLM plans each subtask semantically using `workload`, `acceptance`,
`parallel_safe` and `write_paths`. Routine tasks and image interpretation use
DeepSeek Flash; complex implementation, debugging or review use DeepSeek Pro.
This provider uses the profile's native DeepSeek credentials. It makes no separate
planner request and does not use prompt-length/keyword rules to classify tasks.
Each helper's selected model remains fixed, including while the parent uses Auto.
The route/model label is included in the existing delegation results and progress.

Before any helper is built, the plan validator rejects missing acceptance checks,
invalid paths, conflicting declared write scopes, and tasks marked dependent that
were submitted as a parallel batch. Comparisons cover Windows case and separators.
The parent must submit dependent stages after their prerequisite results arrive.
Acceptance criteria and write scopes are inserted into each new child's initial
context, with instructions to report actual checks, artifacts and unresolved issues.

The parent is instructed to inspect results, integrate them, and use a complex
retry/reviewer when evidence warrants it. Complexity judgments remain LLM-led.
The validator checks declared
write scopes; it cannot prove a helper obeys them. No arbitrary scoring threshold
automatically declares a task verified. Ordinary stop/steer semantics, the two-child
process gate, flat delegation, privacy opt-outs and approval policies are unchanged.

Tests exercise bundled discovery and registry dispatch, safe/invalid parallel plans,
profile separation, stable schema bytes and actual child model requests through an
HTTP mock transport (only DeepSeek destinations, no Nous request). Windows desktop
E2E checks the real settings selection, persisted YAML and a full app restart under
an isolated `MEU_HOME` and Electron user-data directory.

## Persistent project checkpoints (development branch)

Plugin version 1.1 adds `coordinate_project` to the existing delegation toolset
when Meu Coordinator is selected for new sessions. Ordinary delegation remains
available. This is a plugin tool, with no additional core scheduler or model call.
The parent creates a plan with a stable project id, absolute working directory,
task ids, prerequisites and the existing workload/acceptance/write-scope contract.

Set `tool_access: files_only` when an assignment calls for file tools only.
The child can use the parent's available `read_file`, `write_file`, `patch`
and `search_files` tools. Both the advertised tools and the executor apply this
limit. Refused calls appear as errors in the child trace. The choice is saved
with the task and reused after interruption or retry. An omitted choice uses
normal inheritance.

Checkpointed helpers start in the saved local project directory. For a
`files_only` helper, reads and searches must start inside that workspace, and
edits must also match the assignment's `write_paths`. An empty list makes the
assignment read-only. Every patch destination is checked before applying the
patch. Explicit paths through symbolic links or Windows reparse points are
refused. These checks apply to the native file tools and are not OS isolation
against concurrent changes by another process. Other helpers retain their
existing tool policies. When worktree isolation is configured, the project
helper fails to start if the requested checkout cannot be prepared. A
successful isolated edit must be integrated before verifying the project's
original artifact.

`run` selects at most two independent ready tasks (also respecting the configured
native child limit). The existing delegation engine owns children, progress,
stop/steer, provider credentials and budgets. Each child's contract includes the
project directory and the verified prerequisite results. Completed children become
`needs_review` and are saved as their results arrive, even while a sibling runs.
Completion alone never unlocks a dependent task.

The parent runs the acceptance checks through its normal tools, then records
`verify` with the exact attempt number, results/evidence and artifact files.
Successful writing tasks require an artifact in their declared write scope.
SHA-256 fingerprints bind acceptance
to those files: modifications invalidate that task and downstream acceptance.
This records the parent's verification; it is not independent proof that an LLM
actually ran a claimed test. Existing tool policies still own check execution.

Plans/results live under the owning profile's `coordinator/<project>.json`, using
private directories, atomic writes and the existing cross-process filesystem lock.
A new process/session can read `status` and continue the same plan. Acquiring the
lock after a process died turns saved `running` tasks into `interrupted`, never an
automatic replay. The parent inspects existing artifacts/side effects before an
explicit evidenced retry; routine retries use Pro and attempts are capped at three.
A held lock refuses duplicate project dispatch. Independently named projects do
not share this project lock.

The project rehearsal uses a payments CSV with a duplicate and a refund. The
native Flash helper writes the normalized rows, then the Pro helper writes an
incorrect report before its process exits abruptly. A new process keeps Flash's
verified work, detects the interrupted Pro attempt, and retries only after
reconciliation. The parent checks the corrected total and rejects the source CSV
as evidence for the report. The rehearsal uses local files and mocked DeepSeek
responses. It checks orchestration and recovery without measuring model quality.

## OpenClaw comparison, inspected 2026-11-03

Primary documentation and source reference:
[OpenClaw subagents](https://github.com/openclaw/openclaw/blob/99652357adba0bbfcdaa18277b7d26ea9d3dffce/docs/tools/subagents.md).
The comparison is architectural guidance, not a claim of feature parity.

| Observed OpenClaw idea | Meu decision |
| --- | --- |
| [Per-child model and isolated/forked context](https://docs.openclaw.ai/tools/subagents/tool-reference) | Keep explicit Flash/Pro routing and concise task contracts; copy only verified prerequisite results into later tasks. |
| [Child completion requires parent review](https://docs.openclaw.ai/tools/subagents/slash-command) | Persist `needs_review` separately from `verified`; do not equate a finished helper with a finished project. |
| [Retained results and duplicate delivery suppression](https://docs.openclaw.ai/tools/subagents/announce) | Reuse native Meu delegation receipts/transcripts; add project attempt ids and lock ownership, with no second delivery queue. |
| [Parent-child hierarchy, limits and cascading stop](https://docs.openclaw.ai/tools/subagents/nesting) | Retain Meu's existing flat delegation, child cap and stop fan-out while testing this project layer. Increasing nesting is a later measured change. |
| [Background execution and completion events](https://docs.openclaw.ai/tools/subagents/slash-command) | Keep native asynchronous delegation for ordinary background tasks. The new checkpointed `run` is a synchronous bounded batch; background project checkpoint integration remains separate work. |

The useful principles are stable task identity, explicit dependencies, retained
outcomes, clear failure states and review before integration. External-agent ACP
bridges, cloud placement, recursive swarms and authentication sharing are not
required to deliver those principles in Meu. No OpenClaw code or new service
dependency was copied into this implementation.

The implementation was also inspected at that same pinned revision. Its
[run types](https://github.com/openclaw/openclaw/blob/99652357adba0bbfcdaa18277b7d26ea9d3dffce/src/agents/subagents/registry/subagent-registry.types.ts)
represent execution and completion delivery separately. Its
[persistence owner](https://github.com/openclaw/openclaw/blob/99652357adba0bbfcdaa18277b7d26ea9d3dffce/src/agents/subagents/registry/subagent-registry-persistence.ts)
serializes restoration against new admissions, and restored historical rows do
not automatically regain live completion authority. Meu's corresponding project
decision is to retain an unknown/interrupted outcome and require reconciliation
before another attempt, while leaving native receipts/authority with the existing
runtime. A local schema test additionally verifies that the new project tool
actually reaches the model's delegation tool definitions.

The full executor path also passes the live parent only to local handlers that
explicitly declare `parent_agent`. Hosted callbacks and catch-all keyword handlers
do not receive that object. The existing registry execution-timeout metadata is
now available through `PluginContext.register_tool`; project batches request a
one-hour transport budget while retaining native child iteration/stop limits.
This closes the difference between direct registry tests and a real model tool
call. Tests cover both normal executor dispatch and transport exclusion.
