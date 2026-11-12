# MEU Coding Engine

This document describes the Coding Engine **as it is now**: its architecture, the one authoritative module
for each concern, the security boundaries and how to work on it. The `MEU_CODING_ENGINE_PHASE*.md` files
are historical implementation notes: they record why each phase was built the way it was, and some names
in them have since moved or been removed.

## What it does

A coding task goes through a fixed pipeline. Each arrow is a checkpoint the next stage cannot skip:

```
repository intelligence → Architect (plan) → Coder (proposal) ⇄ Reviewer (bounded repairs)
  → APPROVAL (user) → isolated worktree execution → checks → review of the ACTUAL diff
  → keep / reject → optional local commit → integration preview → APPROVAL → integration
  → (optional) push / PR / merge, each with its own preview and APPROVAL
```

The engine never writes to the parent checkout, never runs a model-supplied command, and never commits,
pushes or merges without an explicit, single-use approval bound to exactly what the user saw.

## Authoritative systems

Each concern has exactly one owner. New code extends the owner listed here; it does not add a second one.

| Concern | Owner | Notes |
|---|---|---|
| Coding task state | `task_service.py` (`CodingTaskService`, `Stage`) | One stage machine; mixins split by topic: `task_integration`, `task_remote`, `task_roadmap`, `task_memory`; read-only views in `task_views` |
| Service per profile | `service_registry.py` | Desktop RPC and the paired phone resolve the same service, so a task has one authority across devices |
| Approval (proposal + execution) | `safe_execution.py` | `ApprovalRequest`/`approve`/`ApprovedChange` (sealed) and `ExecutionApprovalRequest`/`approve_execution` with a single-use approval ledger |
| Worktree | `workspace.py` (`MeuWorktreeWorkspace`) over `tools/subagent_worktree.py` | Also owns the unified-diff → V4A conversion and git probes |
| Provider / model routes | `provider_adapter.py` (`resolve_coding_routes`) over `routing_policy.py` | Routes come only from the existing *Models by workload* slots or the main model |
| Memory | `coding_memory.py` | Uses MEU's existing project memory (`tools.memory_tool`); no second memory database |
| Change tracker | `intelligence.py` (`RepositoryIntelligence.refresh_changed_files`) | `execution_review.refresh_changed` feeds executed changes back into it |
| Project model (index, graph, ranking) | `intelligence.py` over `repo_index`, `symbols`, `graph`, `relevance`, `context_builder`, `cache` | `interfaces.py` holds the index data shapes; `coding_interfaces.py` holds the task/plan/proposal/review shapes |
| Retrieval / semantic layer | `semantic_setup.py` (composition) → `semantic_index.py`, `semantic_search.py`, `embeddings.py` | Optional; a failure yields a disabled layer with a reason, the structural index keeps working |
| Audit path | `task_audit.py` | One JSON file per task under `<HERMES_HOME>/coding_tasks/`; `task_recovery.py` rebuilds tasks from it after a restart |
| Remote / GitHub | `task_remote.py` → `remote_ops.py`, `remote_refs.py`, `github_adapter.py` | `pr_preview.py` only builds the local PR draft text that the remote flow offers |
| Checks | `command_policy.py` → `test_executor.py` | Logical checks become allowlisted argv; models never supply commands |
| Commit / integration | `commit_flow.py`, `integration.py` | Both re-verify everything they were approved against |
| Roadmaps | `autonomous_planner.py` (plans only), `task_roadmap.py` (user control), `planner_provider.py` | Every milestone runs as an ordinary coding task |

## Module map

| Area | Modules |
|---|---|
| Index and intelligence | `repo_index`, `python_outline`, `symbols`, `cache`, `graph`, `relevance`, `impact`, `context_builder`, `intelligence`, `interfaces`, `scope` |
| Planning and coding | `architect`, `coder`, `reviewer`, `repair_loop`, `orchestrator`, `edit_strategy`, `schemas`, `checks`, `coding_interfaces` |
| Models | `provider_adapter`, `routing_policy`, `planner_provider`, `embeddings` |
| Execution | `safe_execution`, `workspace`, `command_policy`, `test_executor`, `execution_review`, `coding_session`, `coding_result` |
| Lifecycle | `task_service` (+ `task_integration`, `task_remote`, `task_roadmap`, `task_memory`, `task_views`, `task_audit`, `task_recovery`), `service_registry`, `commit_flow`, `integration`, `pr_preview` |
| Remote | `remote_ops`, `remote_refs`, `github_adapter` |
| Semantic | `semantic_setup`, `semantic_index`, `semantic_search`, `embeddings` |
| Memory and roadmaps | `coding_memory`, `autonomous_planner` |

`import meu_coding` is cheap: the package exports load on first use (PEP 562), so a light module such as
`meu_coding.service_registry` does not import the whole engine.

## Surfaces

- **Desktop:** JSON-RPC `coding.*` methods in `tui_gateway/methods_coding.py`, typed by
  `tui_gateway/contracts/coding.py`; UI in `apps/desktop/src/plugins/meu-coding/`.
- **Phone:** `gateway/mobile_coding.py` uses the same `CodingTaskService` through `service_registry`.
  The device identity comes from the pairing, never from the request body.

## Security boundaries

These boundaries are the reason the engine exists in this form. Do not simplify them away.

- **Approval validation.** A proposal is approvable only after a PASS review. The fingerprint is
  SHA-256 over the canonical operations. Execution approval additionally binds the task, the exact edit
  payload, the target files and their hashes, the previewed result and the repository identity (root,
  branch, HEAD). Approval ids are single-use; a repair revokes the previous id.
- **Stale-approval detection.** Before applying, the worktree base is re-hashed; a difference blocks the
  change as stale. After applying, the actual diff and the file hashes must match the approved preview.
- **Write guards and path validation.** `schemas.safe_path_problem` rejects unsafe paths in model output.
  `scope.is_protected` marks sensitive paths. `safe_execution` refuses writes outside the approved set.
- **Worktree isolation.** All execution happens in an isolated worktree; the parent checkout is only read.
  A check that modifies the worktree, or any commit made during checks, blocks the result.
- **Reviewer boundary.** The Reviewer always uses the strong `coding.review` route and can block but never
  approve. Its state is independent of the planning session.
- **Remote SHA verification.** Push, PR and merge each have their own preview, fingerprint and approval.
  Remote refs are re-read before and after each action. A push is fast-forward only.
- **Secret scrubbing.** The GitHub token only ever goes into the `Authorization` header. Secret-bearing
  files and chunks are never embedded. Memory candidates that hold a credential are refused.

**Intentional duplication.** Some checks run twice on purpose: each layer re-checks instead of trusting
the previous one, so do not merge them.
- Command argv is validated by `command_policy`'s own allowlist/denylist and again by MEU's dangerous-command
  detector.
- Proposal, execution, integration and remote approvals each compute their own fingerprint, because each
  binds different facts.
- Integration and commit re-verify state that execution already checked.

## Errors

Each layer raises its own domain exception, and the RPC layer turns it into an error response:
- `ApprovalError` and `ExecutionBlocked` (approval and execution);
- `ProviderError`, `PlanningError` and `SchemaError` (models);
- `CommitRefused` (commit);
- `PlannerError` (roadmaps);
- `TaskError` (lifecycle; this is what the RPC and phone surfaces report).

There is no separate result/error framework; add to these exceptions rather than creating a new one.

## Configuration

- **Model routes** come from the existing `smart_model_routing` (*Models by workload*) slots or from the
  main model; `routing_policy.CODING_WORKLOADS` maps the workloads `coding.architect`, `coding.simple`,
  `coding.complex`, `coding.review` and `coding.planner` onto those slots.
- **Semantic search** is configured under `coding_engine.semantic` (`provider`, `model`, `dimension`,
  `include_tests`), read only by `embeddings.semantic_settings`. It is off unless configured.

There are no other Coding Engine config keys.

## Storage and cleanup

| Data | Location | Cleanup |
|---|---|---|
| Task audit records | `<HERMES_HOME>/coding_tasks/<task_id>.json` | Kept: they are the recovery and audit trail |
| Semantic store | `<HERMES_HOME>/coding_semantic/<project-digest>.sqlite` | Derived data. A store from another schema is rebuilt; vectors are reused by content hash |
| Extraction cache | per-project cache directory (`cache.py`) | Pruned to the live paths on every analysis |
| Worktrees | created by `tools/subagent_worktree.py` | Removed only on an explicit Reject, through `finalize(discard=True)`: a clean tree is pruned, a dirty one is archived first. Anything uncertain, such as a failed inspection, is kept and reported, never deleted automatically |

After a restart nothing resumes:
- a pending approval expires;
- an interrupted mutating step becomes `interrupted`;
- settled results come back with their durable `ResultRecord`.

## Compatibility code

- **Required now:**
  - `task_recovery` restores audit records written by earlier versions (missing fields default);
  - `semantic_index._migrate` rebuilds a store from another schema;
  - `cache` checks its format version.
- **Migration only:**
  - `gateway/mobile_coding.device_source` records `phone-legacy` for a pairing without a device id.
    Remove it once every stored pairing carries a device id.
  - The retired managed-service selections (`tools/tool_backend_helpers.RETIRED_MANAGED_SELECTION`, a
    legacy `nous` name, `use_gateway: true`) fail closed for configs written before the Nous removal.
    Remove them once a config migration rewrites those keys and older configs are no longer supported.

## Working on it

- **Tests:**
  - Coding Engine: `scripts/run_tests.sh tests/meu_coding`.
  - Upgrade safety: `tests/meu_coding/test_upgrade_migration.py`.
  - Recovery: `test_task_recovery.py`.
  - Attacks on the remote flow: `test_remote_attacks.py`.
  - Approval integrity: `test_approval.py`, `test_safe_execution.py`, `test_phase2_safety.py`.
- **Contracts:** the Pydantic models in `tui_gateway/contracts/` are the one source.
  - Regenerate `apps/shared/src/gateway-contract.generated.ts` and `gateway-contract.openrpc.json` with
    `python scripts/gen_gateway_contracts.py`.
  - `--check` (and `tests/tui_gateway/contracts/test_generated.py`) fails when they are stale.
- **Benchmarks:**
  - `scripts/meu/coding_engine_benchmark.py` for indexing and ranking;
  - `scripts/meu_coding_semantic_benchmark.py` for semantic retrieval.
- **Deferred work** is tracked in `docs/MEU_DEFERRED_WORK.md`, which is also read into coding memory.
