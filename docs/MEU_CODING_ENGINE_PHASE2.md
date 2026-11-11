# Meu Coding Engine — Phase 2: Architect → Coder → Reviewer

Phase 2 adds orchestration and planning on top of the Phase 1 repository intelligence
(`docs/MEU_CODING_ENGINE_PHASE1.md`). It plans a change, collects a proposed edit, reviews
it, repairs it a bounded number of times, and stops at an explicit **approval boundary**.
It never applies an edit. Applying stays with MEU's existing safe tools (`patch`,
`write_file`, approvals, write guards, worktrees), reached through an adapter.

## Architecture

```
User task
   |
   v
Repository Intelligence   (Phase 1, cached; one context query per task)
   |
   v
Architect  ── ImplementationPlan (validated) ──┐
   |                                           │ ImpactAnalyzer (graph only)
   v                                           │ TestPlan
Coder      ── CodeChangeProposal (data only) ──┘ EditStrategyRouter
   |
   v
Reviewer   ── ReviewResult: PASS / FIX / BLOCK
   |
   +---- FIX ---> Coder   (bounded repair loop, default 3 repairs)
   |
  PASS
   |
   v
Approval Boundary   (ApprovalRequest → explicit ApprovalDecision → ApprovedChange)
   |
   v
Existing MEU Safe Execution Layer   (patch / write_file / approvals / worktrees; Phase 3)
```

| Module | Responsibility |
|---|---|
| `coding_interfaces.py` | Frozen data model (task, context, plan, proposal, review, impact, test plan) and the three model protocols |
| `orchestrator.py` | `CodingOrchestrator`, `prepare_context`, `CodingResult`, `OutcomeStatus` |
| `architect.py` | `Architect`, `draft_plan`, `validate_plan`, `PlanningError` |
| `coder.py` | `Coder`: strategy choice, model call, format checks |
| `reviewer.py` | `Reviewer`: rule set plus optional model findings |
| `repair_loop.py` | `RepairLoop`, `Attempt`, `RepairOutcome` |
| `edit_strategy.py` | `EditStrategyRouter`, `ModelProfile`, payload structure checks, `touched_paths` |
| `impact.py` | `ImpactAnalyzer` → `ImpactReport` with explained risk |
| `checks.py` | `build_test_plan`, `CheckRunner` protocol, in-memory syntax check |
| `scope.py` | Path rules: traversal, protected paths, config/security/caller classification |
| `execution.py` | Approval boundary, `MeuToolCallAdapter`, `ExecutionAdapter` / `IsolatedWorkspace` protocols |

Phase 1 modules are reused, not duplicated: the orchestrator calls
`RepositoryIntelligence.find_relevant_context` and `rank`; impact analysis reads the
`RepositoryGraph`; the Architect uses `relevance.parse_query`, `WEIGHTS` and
`is_test_path`. Phase 1 behaviour is unchanged. Its API only grew: `__init__.py` exports
the Phase 2 entry points, and `RepositoryIntelligence.context_with_ranking` returns the
bundle together with the ranking it was built from (`find_relevant_context` now delegates
to it), so the orchestrator does not rank twice.

## Stage flow

`CodingOrchestrator.run(task)` records each stage in `CodingResult.stages`:

1. `refresh` (only when `refresh_paths` is given): re-read just those files.
2. `context`: one `context_with_ranking` call builds a frozen `TaskContext`
   (bundle, ranking, dependencies and reverse dependencies of the focus files, known
   paths, file sizes). Every later stage and every repair attempt reads this same object.
3. `architect`: draft plus validation. On failure the result is `PLANNING_FAILED` and the
   Coder is never called.
4. `coder` → `reviewer`, then `repair` → `reviewer` as needed.
5. `approval_boundary` (PASS only): an `ApprovalRequest` with the proposal fingerprint.

End states: `AWAITING_APPROVAL`, `NEEDS_FIX` (repairs exhausted or stalled), `BLOCKED`,
`PLANNING_FAILED`. None of them has modified anything.

## Interfaces (model-independent)

LLM components sit behind three protocols in `coding_interfaces.py`; tests use fakes.

- `PlanningModel.plan(PlanningRequest) -> ImplementationPlan`. Optional. It receives the
  deterministic draft and may refine it, and the result is validated like any plan.
- `CodingModel.propose(CodingRequest) -> CoderOutput`. Required by the `Coder`. The request
  carries the task, plan, shared context, chosen strategy, the profile's context budget,
  and on repairs the previous proposal and review.
- `ReviewModel.review(ReviewRequest) -> findings`. Optional. Its findings are added to the
  rule findings and the most severe wins, so a model cannot downgrade a rule's FIX/BLOCK.
  The orchestrator refuses a Reviewer that shares the Coder's model instance.

### ImplementationPlan

Summary, files and symbols likely to change, files that stay untouched (protected paths
plus context-only files), steps, `TestPlan`, risk, `ImpactReport`, new files,
assumptions, unresolved questions and safety notes. `validate_plan` rejects:

- traversal, absolute or protected paths;
- an empty target list, or more targets than `max_files`;
- planned files that do not exist (they must be listed as new files);
- new files when the task forbids them;
- no steps;
- code changes with no test check while `require_tests` is set;
- unresolved questions.

Files the user names explicitly are never swapped for ranked guesses. If they are
protected, the plan stops with a question.

### CodeChangeProposal

Operations (`EditOperation`: path, strategy, action, payload), chosen `StrategyChoice`,
assumptions, expected tests, notes, and `format_errors` found by the Coder's structural
check. `affected_files` includes paths named inside V4A or unified-diff payloads.

### ReviewResult

`status` (PASS/FIX/BLOCK), findings by category (correctness, missing requirement,
regression, risky change, scope violation, test gap, unexpected file), repair
instructions, confidence and rationale. The rules:

| Rule | Verdict |
|---|---|
| Path traversal / absolute / protected (`.git/`, `.env`, `node_modules/`, task-protected) | BLOCK |
| Delete without `allow_deletes`, create without `allow_new_files`, over `max_files` | BLOCK |
| File outside the plan or marked untouched (including paths smuggled inside a patch) | FIX |
| Planned file or symbol not addressed; empty proposal | FIX |
| Malformed payload, strategy mismatch, create-existing / update-missing | FIX |
| Whole-file Python that does not parse (`ast.parse`, never executed) | FIX |
| A provided check result FAILED | FIX |
| Plan asks for a new test and no test file is touched | FIX |
| Required check not run yet; whole-file rewrite; security file; high plan risk | note (PASS severity) |

The Coder's own assumptions and notes never influence the verdict. Passing tests do not
imply PASS, because every rule runs regardless.

## Edit strategy routing

`EditStrategyRouter` chooses a format. It is not an editor. Formats map onto existing
MEU executors:

| Strategy | MEU executor |
|---|---|
| `SEARCH_REPLACE` | `patch` (mode `replace`, `old_string`/`new_string`) |
| `V4A_PATCH` | `patch` (mode `patch`) |
| `UNIFIED_DIFF` | converted to V4A (`unified_to_v4a`), then `patch` (mode `patch`) |
| `WHOLE_FILE` | `write_file` |
| delete (any) | `patch` with `*** Delete File:` |

Profiles are data (`ModelProfile`: fnmatch patterns over the model id, preferred and
allowed strategies, architect mode, context budget, small-file whole-rewrite limit).
Built in: `deepseek-pro` (V4A, architect mode, 24k context) and `deepseek-flash`
(search/replace, 8k). Any other model gets `safe-default`: search/replace, which MEU's
replace mode refuses when the anchor is ambiguous or missing. `register()` adds profiles,
and later registrations win. Selection is deterministic for a given model id, hint and
requested strategy.

## Repair loop

One initial proposal plus at most `max_repairs` repairs (default 3). It stops on PASS, on
BLOCK, at the limit, on a FIX with no actionable instruction, or when a repair repeats the
previous proposal. Each `Attempt` (number, proposal, review) is kept in
`CodingResult.attempts`. A repair keeps the original strategy and receives the specific
repair instructions.

## Impact analysis

`ImpactAnalyzer(graph).analyze(files, symbols)` reports:

- direct and reverse dependencies;
- affected tests (test-file dependents, tests by stem, tests within two import hops);
- touched configuration;
- UI/API callers among the dependents (`web/`, `apps/`, `api/`, `routers/`, `.tsx`, …).

Risk is the maximum of explained reasons:

| Reason | Level |
|---|---|
| Security-sensitive path (auth, token, approval, sandbox, guard, …) | HIGH |
| ≥ 25 reverse dependencies; symbol used by ≥ 5 other files | HIGH |
| Public API (non-underscore symbol used elsewhere) changed | MEDIUM |
| Configuration file touched; ≥ 8 reverse dependencies; no tests found | MEDIUM |
| New file | LOW |

## Test plan

`build_test_plan` lists checks by kind (`SYNTAX`, `LINT`, `UNIT_TEST`, `PROJECT_COMMAND`,
`BUILD`), each with targets and an optional descriptive command. Nothing in `meu_coding`
runs them. `CheckRunner` is the seam for MEU's approved terminal tooling (Phase 3).
Results come back as `CheckResult` (keyed by `CheckSpec.key`) and are passed to
`run(task, check_results=...)` for review.

## Approval boundary

- `ApprovalRequest.for_review` accepts only a PASS review and stores a SHA-256
  fingerprint of the exact operations.
- `approve(request, decision)` requires `approved=True`, a named approver, a fingerprint
  matching the request, and an unchanged proposal. Any edit after review breaks the match.
- `ApprovedChange` cannot be constructed directly, because it is sealed by a
  module-private token.
- `MeuToolCallAdapter.tool_calls(approved_change)` returns `ToolCall(name, args)` data for
  MEU's own `patch` / `write_file` tools. The caller dispatches them through MEU's normal
  tool path, so sensitive-path checks, stale-write refusal, write-approval gating, V4A
  validation and per-path locks all still apply.
- `ExecutionAdapter` and `IsolatedWorkspace` are Phase 3 protocols. `IsolatedWorkspace`
  is to be built on the existing worktree system (`tools/subagent_worktree.py`): open a
  worktree, apply, run checks, show the diff. Merge or commit stays a separate approved
  step.

## Safety guarantees

- No Phase 2 module writes files, spawns processes, runs git, evaluates code, imports
  `tools/` or `agent/`, or reads config or credentials. `tests/meu_coding/test_phase2_safety.py`
  runs the whole pipeline with process spawning, `eval`/`exec`, write-mode `open` and
  `os` mutations made to raise, against a repository that would drop marker files if
  imported. It checks that the tree is byte-identical afterwards.
- Every stage output is a frozen dataclass, so later stages cannot alter earlier results.
- Scope is enforced twice: by `validate_plan` and again, independently, by the Reviewer
  (which also reads paths inside patch payloads). MEU's write guards remain a third layer
  at execution time.
- The loop is bounded, so it cannot retry forever.
- No network, providers, API keys or new dependencies (standard library only).

## Integration with Phase 1 and performance

The orchestrator takes an existing `RepositoryIntelligence` (ideally the cached, already
analyzed one) and makes one context query per task. It calls `analyze_repository` only
if nothing is indexed yet, and `refresh_changed_files(paths)` only when given paths.
`test_one_task_scans_the_repository_at_most_once` asserts:

- zero indexer scans across a three-attempt task;
- exactly one `context_with_ranking` call, and no ranking beyond Phase 1's own rank,
  deepen, re-rank;
- every Coder request receiving the same context object.

Impact analysis and review are graph and in-memory work only.

Measured on this repository (21.7 k files, Windows, stub coder, index already built;
scratch benchmark, not committed):

| Task | First run | Repeat |
|---|---|---|
| "Fix `SymbolExtractor` fallback in meu_coding/symbols.py" (2 attempts) | 1.14 s | 0.49 s |
| "resolve_gateway_approval_card should keep the actor in tools/approval.py" | 3.01 s | 0.64 s |

There were no indexer scans during any task. A first run includes Phase 1's lazy deep
parse of the ranked files. Removing the duplicate ranking cut the repeat cost from
1.25–1.38 s to 0.49–0.64 s. The remainder is Phase 1 ranking of broad queries (thousands
of candidate files for common words) plus about 0.2 s of impact analysis, which builds a
test-by-stem index once per task.

## Current limitations

- The deterministic Architect plans from ranking signals: it picks files with an exact
  symbol or explicit-path match, otherwise the top ranked file, and records that as an
  assumption. Richer plans need a `PlanningModel` (Phase 3).
- The Reviewer checks scope, structure, requirements and declared results. It cannot judge
  semantic correctness without a `ReviewModel` or real test results.
- Symbol coverage for body edits is inferred from the file the ranking matched the symbol
  in, not from line spans.
- Payload checks are structural. Exact applicability (anchors, context lines) is checked
  by MEU's `patch` tool at execution time.
- Impact analysis inherits Phase 1's graph precision. References exist only for
  deep-parsed files, and dynamic imports are not resolved.
- No real `CodingModel`, `CheckRunner`, `ExecutionAdapter` or `IsolatedWorkspace`
  implementation exists yet (Phase 3).
