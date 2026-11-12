# Meu Coding Engine — Phase 3: providers, safe execution, isolated worktrees

> **Historical implementation notes.** This records how the phase was built and why. The current
> system is described in [MEU_CODING_ENGINE.md](MEU_CODING_ENGINE.md); names here may have moved or
> been removed since.

Phase 3 connects the Phase 2 pipeline (`docs/MEU_CODING_ENGINE_PHASE2.md`) to:

- MEU's real model providers;
- MEU's existing patch engine, file writer, worktree system, diff collector and dangerous-command detector.

An approved change can now be applied and tested. This happens only in an isolated
worktree, and only through those existing systems. The engine then reviews the actual
result and stops before any commit.

```
User Task
   |
Repository Intelligence      (Phase 1; one shared context per task)
   |
Architect                    (provider: complex route)
   |
Coder Proposal               (provider: complex route, or routine route for simple low-risk edits)
   |
Reviewer                     (rules + independent provider session)
   |
Approval                     (ExecutionApprovalRequest: exact preview diff + fingerprint v2)
   |
Isolated Worktree            (tools/subagent_worktree.py)
   |
Safe Patch Apply             (tools/patch_parser.py V4A engine, file_operations_native.atomic_write)
   |
Tests                        (command policy → bounded_probe_run, scrubbed env)
   |
Actual Diff Review           (tools/working_diff.py + changed-file re-extraction)
   |
Reviewer
   |
PASS / FIX / BLOCK
   |
STOP BEFORE COMMIT
```

## Modules

| Module | Role |
|---|---|
| `schemas.py` | Strict JSON schemas for Architect, Coder and Reviewer replies |
| `provider_adapter.py` | MEU provider stack behind `PlanningModel`, `CodingModel` and `ReviewModel`; routes; retries; call metadata |
| `command_policy.py` | Turns a logical check into an allowlisted argv; blocklist plus MEU's dangerous-command detector |
| `test_executor.py` | `CheckRunner` that runs planned argv in the worktree through MEU's bounded runner |
| `workspace.py` | Worktree creation and finalization, worktree-confined file ops, V4A conversion, diff reading, read-only git facts |
| `safe_execution.py` | Fingerprint v2, single-use approval ledger, `SafeExecutionAdapter`, `ExecutionResult` |
| `execution_review.py` | Review of the actual diff and results, plus the targeted re-extraction of changed files |
| `coding_session.py` | `CodingSession`: start → approve → execute → review → (repair → new approval) |

Phase 2 changes were additive:

- `CodingResult.context` exposes the shared `TaskContext`.
- `reviewer.verdict()` is now public.

## Provider integration

- **Calls.** Requests go through `agent.auxiliary_client.call_llm(provider=…, model=…)`.
  Credentials, base URLs, key rotation, rate limits and fallbacks are MEU's own. The
  Coding Engine never reads, stores or logs a key. `provider_has_credentials()` only
  asks MEU's resolver whether a key exists.
- **Routes.** `routes_from_meu_config()` reads the existing **Models by workload** policy
  (`smart_model_routing`):
  - the `complex` route serves the Architect, the Coder and the Reviewer;
  - the `routine` route serves the Coder for single-file, low-risk first attempts.

  Explicit `CodingRoutes` can be passed instead. No model name is hard-coded, and no new
  config key or secret store was added.
- **Independence.** `provider_models()` gives each role its own session and call history.
  The Phase 2 orchestrator still refuses a Reviewer that shares the Coder's model
  instance.
- **Validation.** Every reply passes `parse_json_object` and then a role validator:
  - Keys that try to steer execution are rejected anywhere in the JSON: `command`, `run`,
    `shell`, `approved`, `approval`, `fingerprint`, `env`, and similar.
  - Paths must be plain, repository-relative and free of shell metacharacters.
  - Deletes are refused.
  - The edit strategy comes from the router, never from the model.
  - A model's `pass` verdict grants nothing.
- **Retries.** A malformed reply is retried once, with the validation errors attached.
  Provider errors are not retried here, because MEU's client already has its own policy.
- **Controlled failures.**
  - Architect failure: `PlanningError`, so the result is `PLANNING_FAILED`.
  - Coder failure: no edits, so the result is `NEEDS_FIX` with nothing to approve.
  - Reviewer failure: a BLOCK finding.
- **Metadata.** `ProviderSession.calls` records role, route, attempts, seconds, ok and a
  short error. It never records content.

## Approval fingerprint (v2)

`SafeExecutionAdapter.prepare()`:

1. Re-validates scope.
2. Reads the repository identity: root, branch and HEAD.
3. Reads the target files in the parent, read-only.
4. Applies the proposal **in memory with MEU's own V4A engine** to produce the exact
   result and a preview diff.

The resulting `ExecutionBinding` covers:

- the task digest (description, explicit files, constraints, model id, recent diff);
- the Phase 2 proposal fingerprint, and a payload digest over the combined patch and any
  whole-file contents;
- the sorted target files;
- base text hashes of the targets (UTF-8, BOM and line endings normalised, so a CRLF
  checkout is not a change);
- the expected result hash of every file the preview wrote;
- the repository root, branch and base commit.

The approval fingerprint is `sha256` over the whole binding. `approve_execution()` needs
`approved=True`, a named approver, the matching approval id and the matching
fingerprint. It recomputes the proposal, payload, task and target digests, and it also
passes through Phase 2's `approve()`. `ApprovedExecution` cannot be built directly.

The adapter's ledger issues each approval id once (`pending`). Executing marks it `used`,
even when the execution fails, and a repair `revoke`s the old id. Stale or reused
approvals are refused.

## Execution flow (`SafeExecutionAdapter.execute`)

1. Verify the sealed approval, the ledger state, the binding and the scope (again).
2. Verify the parent identity (root, branch, HEAD) and every target's base hash.
3. Open a worktree with `create_subagent_worktree` (branch `hermes-subagent/subagent-coding-<id>`).
   Its base commit and each target's hash must equal the binding; anything else is stale
   and blocks.
4. Apply through `WorktreeFileOps`. Every path is confined to the worktree root, symlinked
   components are refused, deletes and moves are refused, and MEU's
   `_check_sensitive_path` and internal-display-text guards run per write. The patch
   itself goes through `parse_v4a_patch` and `apply_v4a_operations`, which validate every
   hunk before writing anything; writes use `atomic_write`.
5. Read the actual diff (`collect_working_diff(mode="all")`). The changed files must
   equal the approved preview's files, and every file's text hash must equal the approved
   result. Otherwise the result is BLOCK.
6. Run the plan's checks (below) in the worktree. The diff is read again afterwards, and
   a check that changed the worktree is BLOCK.
7. `rev-list --count base..HEAD` must be 0: any commit is BLOCK.
8. Return `ExecutionResult`:
   - status and reasons;
   - approval id and fingerprint;
   - worktree path, branch and base;
   - files changed, additions, deletions, the actual diff;
   - each executed check (argv, status, output tail, seconds);
   - commit count and status, the worktree state, and timings.

All edit strategies become V4A input for MEU's engine:

- search/replace becomes a V4A hunk;
- a unified diff goes through `unified_to_v4a`;
- creating a file becomes `Add File`;
- a whole-file update is written once through the same confined writer.

## Test execution

`CommandPolicy` builds argv from a `CheckSpec`. Models cannot supply commands.

| Check | argv |
|---|---|
| syntax | `<running python> -m py_compile <existing .py targets>` |
| lint | `<ruff via hermes_platform.locate_command> check --no-cache <targets>` (skipped if ruff is absent) |
| unit_test | `<running python> -m pytest -q -p no:cacheprovider <existing test files>` |
| build / project | only an exact argv registered by trusted code |

Every argv is validated before it runs:

- no shell metacharacters or NUL;
- blocked programs: git, rm, del, format, diskpart, reg, cmdkey, powershell, cmd, sh,
  pip, uv, npm, pnpm, curl, …;
- blocked patterns: `git reset/clean/checkout/switch/merge/rebase/push/…`, `--hard`,
  `--force`, `rm -r`, `del /s`, `Remove-Item -Recurse`, package installs;
- python only with `-m pytest` or `-m py_compile`, ruff only with `check` and no fixes;
- finally MEU's `tools.approval_detection.detect_dangerous_command`.

Processes start through `hermes_cli._subprocess_compat.bounded_probe_run`:

- argv only, no shell;
- a Windows job object or POSIX process group, tree-killed on timeout;
- environment from `hermes_subprocess_env(inherit_credentials=False)`, so provider and
  bot keys are removed;
- `PYTHONDONTWRITEBYTECODE=1` and an empty `PYTHONPATH`;
- `cwd` is the worktree.

## Repair rules

`CodingSession.repair()` runs only after an actual-diff review returned FIX with concrete
instructions, at most `max_repairs` (3) times. Each repair:

1. calls the Coder with the reviewer's findings;
2. produces a **new** proposal;
3. runs the Phase 2 review on it;
4. prepares a **new** approval with a new id, revoking the old one.

`execute()` then needs a new decision for that id, so the old approval cannot drive a
repair. Repairs are full proposals against the approved base and run in a fresh
worktree. Earlier worktrees are kept for comparison.

## Rollback and cleanup

The parent checkout is never written, so there is nothing to roll back there. Worktree
cleanup follows the existing rules (`finalize_subagent_worktree`):

- **Nothing written** (blocked before or at apply): `prune=True`. The existing code
  removes a clean tree only when its probes prove it clean and commit-free, and keeps it
  otherwise.
- **Anything written** (success or failure): `prune=False`. The tree and its branch are
  always kept for inspection.

No merge, push, branch deletion or destructive cleanup is ever run against the parent.
Creating a worktree does add a branch ref and the `.worktrees/` registry entry, as for
MEU's delegated subagents.

## Performance

Measured on this repository (21.7k files, Windows) with a stub coder, without executing
anything in it:

- **Fast index:** 25.1 s, built once.
- **Plan, propose, review and approval prepare:** 1.62 s on the first task (0.95 s of it
  Phase 2) and 0.73 s on a repeat (0.40 s). `prepare` is about 0.3 s: identity probes plus
  an in-memory preview.
- **Coder response processing:** 0.30 ms per 80 KB reply.
- **Targeted refresh of changed files:** 0.67 s for 3 files, including a 6,967-line
  adapter. Only the changed files are re-extracted, never the tree.
- **Sample repository, real worktree:**
  - verify 0.29 s;
  - apply 0.58 s (worktree creation plus patch);
  - checks 1.5 s (py_compile, ruff, pytest);
  - actual review under 10 ms.

No stage re-scans the repository; a test asserts zero indexer scans across a full
session.

## Security boundaries

- **No direct process or code execution.** Phase 3 modules contain no `subprocess`,
  `os.system`, `eval`, `exec`, `shell=True` or `Popen`. Processes start only via
  `bounded_probe_run`, for allowlisted checks, and `bounded_git_probe`, for read-only
  `rev-parse` and `rev-list`.
- **One write path.** The only filesystem write is `atomic_write` inside
  `WorktreeFileOps` (worktree-confined, guarded). Worktree creation and cleanup are
  `tools/subagent_worktree.py`'s own.
- **Read-only git.** Phase 3 code never runs mutating git. The worktree module runs its
  own `worktree add`, `remove` and `archive` under its existing hardening.
- **Secrets.** No secrets, API keys or temporary paths are hard-coded. Child processes
  get a credential-scrubbed environment.
- **Bypass attempts that fail safely**, each covered by a test:
  - `../` and absolute paths, and paths with shell metacharacters;
  - protected files, and unexpected files (including files smuggled inside a patch);
  - `git reset --hard` and `git push` (as commands, or as keys in a reply);
  - a proposal or task changed after approval;
  - self-approval keys, and a forged `ApprovedExecution`;
  - a moved HEAD or branch (workspace identity), and a parent target edited after
    approval;
  - checks that modify the worktree;
  - reuse of a used or revoked approval.

## Known limitations

- Execution needs a git repository with at least one commit, and the local terminal
  backend, because a host worktree is invisible to Docker/SSH backends.
- Repairs are full proposals against the original base, not increments on the previous
  worktree.
- The Coding Engine never deletes or moves files.
- Text files must be UTF-8.
- Tests run real repository code inside the worktree. That is the point of running
  them, but it means approval should be given only for repositories the user trusts.
  The environment is scrubbed of credentials; it is not a sandbox.
- Ruff is used only when `hermes_platform` finds it. Build and project commands need
  trusted registration.
- Approval and diff review have no UI yet; `ExecutionApprovalRequest.summary()` and
  `preview_diff` are the data for Phase 4.
- The live provider test (`tests/meu_coding/test_phase3_live_provider.py`, `-m live`) runs
  only when Models by workload and credentials are configured. It was skipped here.
