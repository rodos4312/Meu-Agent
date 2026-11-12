# Meu Coding Engine — Phase 4: desktop approval, diffs, keep/reject, local commit

> **Historical implementation notes.** This records how the phase was built and why. The current
> system is described in [MEU_CODING_ENGINE.md](MEU_CODING_ENGINE.md); names here may have moved or
> been removed since.

Phase 4 brings the Phase 1–3 engine into the desktop app as a user-facing workflow: approval
cards, diff views, keep/reject decisions and an optional local commit. Integrity rules carried
over from Phase 3 stay in force, and one is added: a decision is single-use and exact.

```
Coding request (Coding page, current workspace)
   → Repository Intelligence → Architect → Coder → Reviewer
   → APPROVAL PREVIEW (exact fingerprint, proposed diff)
   → user APPROVE / REJECT
   → isolated worktree → MEU patch engine → tests → ACTUAL DIFF review
   → KEEP / REJECT
   → (PASS + KEEP only) COMMIT LOCALLY — preview, editable message, explicit confirmation
   → STOP (no push, no merge)
```

## Components

| Layer | Module |
|---|---|
| Task lifecycle | `meu_coding/task_service.py` (`CodingTaskService`, `Stage`, `TRANSITIONS`) |
| Views | `meu_coding/task_views.py` (snapshot; user-facing error wording) |
| Audit | `meu_coding/task_audit.py` (one JSON per task) |
| Commit | `meu_coding/commit_flow.py` (`prepare_commit`, `confirm_commit`) |
| Routing | `meu_coding/provider_adapter.py::resolve_coding_routes` |
| RPC | `tui_gateway/contracts/coding.py`, `tui_gateway/methods_coding.py` (`coding.*`, profile-scoped) |
| Desktop | `apps/desktop/src/plugins/meu-coding/` (`plugin.tsx`, `page.tsx`, `api.ts`, `model.ts`) |

The desktop surface is a bundled plugin: a `/coding` page, a sidebar entry "Coding" and a
command-palette entry. It uses only the plugin SDK (`host.request`, `host.state.cwd`) and
changes no core desktop file. The page polls `coding.get` while a stage is running. The
selected task lives in module state, so leaving the page and coming back shows the
current stage; nothing restarts.

## Stages

```
analyzing → planning → coding → reviewing ⇄ coding → awaiting_approval
awaiting_approval → executing → testing → reviewing_diff → awaiting_keep_reject
awaiting_keep_reject → ready_to_commit (PASS + KEEP) → committed
awaiting_keep_reject → kept (KEEP without PASS: preserved, never committable)
awaiting_keep_reject → coding (repair) → … → awaiting_approval (new approval)
any reviewable state → rejected ; failures → blocked / failed
```

Transitions are a table, `TRANSITIONS`. An invalid move raises, and a test covers this.

## Approval UX

The approval card shows:

- the task, the Architect's plan summary and steps;
- the target files, the protected paths and the files kept untouched;
- the edit strategy with the router's reason;
- the risk level and the impact summary (dependents, affected tests, reasons);
- the checks that will run;
- the worktree target (repository root, branch, base commit; a new isolated worktree);
- the **full fingerprint**, and the **PROPOSED DIFF**: the exact result previewed with
  MEU's own patch engine.

Actions are **Approve `<fingerprint>`**, **Reject**, and **View details**, which shows
the approval id, the full fingerprint, the per-file change list, the pre-review rationale
and the models used.

What a decision carries, and how the backend treats it:

- The `coding.decide` parameters are built from the approval on screen: its approval id
  and its 64-character fingerprint. A vague decision such as `"allow coding"` fails
  contract validation.
- The backend accepts a decision only if both values equal the **current** pending
  approval.
- The stage leaves `awaiting_approval` under the task lock **before** execution starts.
  A replayed decision, a second click or a second device is refused with "This approval
  was already used or the task has moved on."
- A repaired proposal gets a new approval id and fingerprint, and the old approval is
  revoked. The decision is recorded with approver and device.

## Diff flow

- **PROPOSED DIFF** is `ExecutionApprovalRequest.preview_diff` (Phase 3), computed once
  when the approval is prepared.
- **ACTUAL DIFF** is `ExecutionResult.diff`, read from the isolated worktree with MEU's
  `tools/working_diff.py`.

Neither is recomputed for display. Phase 3 compares the actual changed files and text
hashes with the approved preview; any difference blocks with "Actual diff does not match
approved proposal." The task then has nothing to keep or commit, and it needs a new
approval.

## Keep / reject

- **Keep** after `awaiting_keep_reject`:
  - Reviewer PASS on an executed result → `ready_to_commit`.
  - Otherwise → `kept`: the worktree is preserved and the result can never be committed.
- **Reject**, from any reviewable state: every attempt's worktree goes through
  `finalize_subagent_worktree(prune=True)`, the existing rules:
  - a clean, commit-free tree is removed;
  - a tree with work is archived to `refs/hermes/archive/…`, then removed with its branch
    kept;
  - when probes or archiving fail, the tree is kept.

  If cleanup raises or cannot be proven safe, the tree is preserved and the page says
  "Worktree cleanup could not be proven safe — preserved for inspection." The parent
  checkout is never cleaned.
- **Reject before execution** revokes the approval. No worktree is created.

## Commit workflow

**Commit locally…** appears only in `ready_to_commit`: approved, executed, tested,
actual-diff Reviewer PASS, user Keep.

1. `coding.commit.prepare` re-reads the worktree diff. It must equal the reviewed diff
   and file list, and the worktree must have no commit yet. It returns the files, diff
   stat, worktree branch and path, the parent branch (unchanged), a **suggested** message
   (task, files, reviewer summary) and a token bound to the diff.
2. The user edits or accepts the message, ticks the confirmation and presses **Commit**.
   `coding.commit.confirm` requires `confirmed: true`, the token, and a message that is
   not empty. It then re-checks the diff, the branch and the git identity.
3. It runs `git add -- <reviewed files>` and checks that the staged files are exactly
   those, then runs `git commit --file=-`. Both go through MEU's hardened runner:
   `bounded_probe_run`, `harden_git_argv`, `noninteractive_repo_git_env`, with hooks,
   pager, editor, credential helpers and filters disabled.
4. It verifies that the new commit's parent is the base commit and that the parent
   checkout's branch and HEAD are unchanged.

The commit lands **on the worktree's own branch**. There is no push, no merge and no
force flag. A missing `user.name` or `user.email` is reported as an action for the user;
no identity is ever invented.

## Models by workload

`resolve_coding_routes(config)` reads only existing settings:

| Role | With Models by workload (`smart_model_routing.routes`) | Without |
|---|---|---|
| Architect | `complex` route | main model (`model.provider` / `model.default`) |
| Coder, simple low-risk single file | `routine` route | main model |
| Coder, otherwise and all repairs | `complex` route | main model |
| Reviewer | `complex` route, own session | main model, own session |

There is no new routing system and no new config key. If no model is configured at all,
`coding.start` answers "No coding model is configured — choose a main model or Models by
workload in Settings."

## Live DeepSeek smoke test

Run once, on 2026-11-11, with the user's existing configuration, in a temporary home
holding copies of the configuration and keys (deleted right after) and a temporary git
repository:

| Item | Result |
|---|---|
| Routing | `main_model_fallback`. Models by workload is enabled but has no routes, so the main model `deepseek:deepseek-flash` served all roles |
| Architect / Coder / Reviewer (proposal) / Reviewer (actual diff) | valid JSON on the first attempt; 8.2 s / 8.3 s / 3.1 s / 3.1 s |
| Proposal | `multiply(a, b)` in `calc/ops.py`, plus a test in `tests/test_ops.py`, search/replace, 2 files |
| Execution | isolated worktree; verify 0.40 s, apply 0.21 s, checks 1.50 s |
| Checks | py_compile passed, ruff passed, pytest passed (2 passed) |
| Reviewer | PASS |
| Parent | tracked files unchanged, HEAD unchanged, no remote, no commit |

The first attempt was refused by design: the Architect listed style questions as
"unresolved questions", which stop the task. The Architect prompt now reserves that field
for blocking questions and records style choices as assumptions; the second run passed.

In a brand-new, unprovisioned home, the first `working_diff` call provisions MEU's managed
runtime (~144 s, "Installing Python dependencies"). This is a one-time cost of a fresh
home, not of the engine. An installed Meu already has that runtime.

`tests/meu_coding/test_phase3_live_provider.py` (`-m live`) now uses the same route
resolution. It still skips when no route or credentials are available, which is always
the case under `scripts/run_tests.sh` because that runner clears credentials.

## Mobile approval: interface defined, UI deferred

Android pairs with the desktop through the mobile relay and a deliberately narrow,
phone-facing surface (`docs/meu/ANDROID_COMPANION.md`): sessions, prompts, helper status.
Showing coding approvals there needs a new phone-facing adapter and new Android screens,
which is broader than this phase. The backend already enforces everything a phone would
need:

- **Pending approval data:** `coding.get` → `task.approval` has the exact id, fingerprint,
  targets, strategy, risk, checks and diff. A phone summary should project only: task,
  project name (not the desktop path), risk, affected files, a short diff summary,
  expected tests and stage/worktree status.
- **Decision:** `coding.decide {task_id, approval_id, fingerprint, decision, device}`.
  It accepts the exact current proposal only, is consumed once, is refused when stale or
  replayed, and records the device.
- **Remaining work:** a phone-facing projection that filters to the paired profile and
  hides paths, relay authorization for `coding.decide`, and Android screens.

## Audit trail

`<HERMES_HOME>/coding_tasks/<task_id>.json` is written atomically with MEU's
`atomic_write`. It holds:

- task id, project and short description;
- stage history with times;
- model routes (provider:model) and the route source;
- plan hash, proposal fingerprint, approval id and fingerprint;
- the decisions (approve or reject, approver, device, time);
- worktree path, branch and base;
- the checks and their statuses;
- the Reviewer verdict, keep/reject, the commit hash, and an error summary.

It never holds keys, credential payloads, prompts, diffs or file contents; saving refuses
any field whose name looks like a secret.

After a backend restart, tasks are listed from their audit records. A task that was
still in progress is shown as failed, with "Meu restarted while this task was <stage>;
nothing continues automatically" and the preserved worktree path. Nothing re-runs.

## Security boundaries

- **No approval bypass.** Only the backend changes stage. Decisions must match the
  current approval id and fingerprint exactly, and Phase 3's `approve_execution` and
  single-use ledger still run underneath.
- **No duplicate execution.** The stage changes under the task lock before the
  execution thread starts.
- **No stale approvals.** A changed proposal, task, target file, HEAD or branch blocks
  (Phase 3). After a repair the old approval is revoked.
- **No cross-device replay.** A second device's decision for the same approval is
  refused, because the first consumed it. A different proposal with the same title has
  a different id and fingerprint, so it is refused too.
- **No raw shell or new writes.** Phase 4 runs no raw shell and adds no new filesystem
  writes in projects. The only new writes are the audit JSON in the profile home and the
  commit inside the worktree, through the hardened git runner.
- **No push, merge or force.** No branch change on the parent, and no automatic commit
  or dependency installation.
- **Profile scope.** Every `coding.*` method is profile-scoped. Background threads
  inherit the caller's profile context (`spawn_context_thread`), so routes, keys and
  audit files belong to the addressed profile.

## Known limitations

- **Desktop TypeScript not compiled or run here.** This checkout has no installed node
  dependencies. The UI logic tests (`model.test.ts`) were run with Node's TypeScript
  support and a minimal `vitest` shim; a type-check with another checkout's TypeScript
  showed only missing-React-type noise, which the existing pages produce too. Run
  `pnpm install` and the desktop tests before shipping.
- **Live progress.** The page polls (1.5 s while busy) instead of subscribing to events.
- **Mobile.** The approval UI is deferred; see the interface above.
- **Restarts.** A task restored after a restart is read-only. A new task must be started.
- **Commits stay on the worktree branch.** Merging that branch into the project is a
  deliberate manual step (Phase 5).
- **Fallback routing has no simple-coder shortcut.** Without Models by workload, every
  role uses the main model.
