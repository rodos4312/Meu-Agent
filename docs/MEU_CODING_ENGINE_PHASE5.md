# Meu Coding Engine — Phase 5: integration, PR preview, workload routing, phone approvals

Phase 5 completes the local lifecycle of a coding result and makes it work across devices:

- a durable result record and recovery after a restart;
- a controlled, isolated integration toward the target branch, with drift and conflict
  analysis;
- a local PR preview;
- coding workloads on the existing Models by workload settings;
- a deterministic complexity classifier;
- coding approvals on the paired Android phone, sharing the desktop's single task authority.

Nothing in Phase 5 pushes, merges into a target branch, creates a remote branch, opens a PR,
installs dependencies or runs destructive git commands. The 97 known failures of the full
desktop test suite are pre-existing technical debt and were not touched. Phase 5 adds no new
failure there.

## Result lifecycle

`meu_coding/coding_result.py::ResultRecord` is the durable form of an executed result. It
records:

- the task id;
- the proposal and approval fingerprints, and the approval source (desktop or mobile);
- the worktree branch and path, the base commit and the target branch;
- the result commit and the changed files with line counts;
- the tests and planned checks;
- the Reviewer verdict and rationale;
- a digest of the reviewed diff.

States are appended only by the operation that earned them, never inferred:

```
EXECUTED → TESTED → REVIEWER_PASS → KEPT → COMMITTED_IN_WORKTREE → READY_TO_INTEGRATE → INTEGRATED
                                         ↘ REJECTED            (any point: BLOCKED)
```

Task stages added: `integration_preview`, `integrating`, `integrated`, `interrupted`. The
`committed` stage is now labelled **Ready to integrate**. Keep, reject, commit and integration
all work from the result record, so they behave the same for live and restored tasks.

## Integration workflow

```
worktree result commit  (Reviewer PASS + Keep + local worktree commit)
        │  Preview integration         read-only: base vs target head, drift, merge-tree verdict
        ▼
integration preview  ── Cancel ──► back to Ready to integrate
        │  explicit approval naming the preview token (+ confirmation)
        ▼
new isolated worktree from the target head   (existing worktree system)
        │  git cherry-pick <result commit>   (inside that worktree only; abort there on failure)
        ▼
validation: planned checks via the command policy (syntax, lint, targeted tests)
        ▼
final diff (target head..integration commit) → Reviewer (rules + independent model when live)
        ▼
INTEGRATED (on hermes-subagent/subagent-coding-integrate-<task>)  or  BLOCKED
        ▼
PR preview (local)  — Edit / Cancel / Approve PR creation later
```

- **Integration branch.** It follows the existing worktree convention
  (`hermes-subagent/…`), because the worktree system names branches itself. The target
  branch, the parent checkout and every remote stay untouched. Merging the integration
  branch is Phase 6.
- **Strategies offered.**
  - `APPLY_COMMIT`: replay onto an integration branch, the default safe local strategy.
  - `CHERRY_PICK_PREVIEW`: the preview above.
  - `CREATE_PR_PREVIEW`: always available. When integration is blocked, it is the only
    strategy offered.
- **Re-review.** If replaying onto a moved target changes the patch (different
  `git patch-id`), the result is flagged, and the final diff is always reviewed again.

## Branch drift

The preview compares the task's base commit with the current head of the target branch:

| Status | When | Integration |
|---|---|---|
| CLEAN | target head == base | allowed after approval |
| NEEDS_REBASE_OR_REPLAY | target moved, `git merge-tree --write-tree` reports no conflict | allowed after approval, replayed and re-validated |
| CONFLICT | merge-tree reports conflicts | blocked |
| BLOCKED | the result commit is missing or not on the base, the target branch is missing, or the committed files differ from the reviewed ones | blocked |

The preview explains the drift precisely: the target commits since the base (up to 20),
the files they changed, the files that overlap with the result, and the conflicting paths.
Approval names the preview token, which binds the result commit, the target head, the
status and the files. If the target moves after the preview, the integration blocks and
asks for a new preview. Nothing is ever rebased or merged silently.

## PR preview

`meu_coding/pr_preview.py` builds the preview locally. It contains:

- title, summary, why;
- the files changed and the test results;
- risk, the Reviewer result and known limitations;
- source and target branch.

The user can edit it, cancel it, or mark it **approved for creation later**. Creating a
remote PR is unavailable in this phase:

- `remote_available` is always false;
- with no remote, the message says "No git remote is configured for this repository — PR
  creation is unavailable";
- no remote is ever invented.

## Models by workload routing

Coding workloads are names for the **existing** Models by workload slots
(`agent/workload_routes.py`). There is no parallel router:

| Workload | Slot | Fallback |
|---|---|---|
| `coding.architect` | complex | main model |
| `coding.simple` | routine (else complex) | main model |
| `coding.complex` | complex | main model |
| `coding.review` | complex, own session | main model |

### Complexity classifier

`meu_coding/routing_policy.py::classify` is deterministic and only picks the coder
workload; it never changes what needs approval.

- **HIGH_RISK:** a security-sensitive or configuration file, a high-risk plan, or 25 or
  more dependents.
- **COMPLEX:** 3 or more files, 8 or more dependents, a public API change, a medium-risk
  plan, more than 6 steps, or more than a code file plus its test.
- **SIMPLE:** otherwise.

Only the first attempt of a SIMPLE task uses `coding.simple`. Repairs and
COMPLEX/HIGH_RISK tasks use `coding.complex`.

### What is recorded

Every task records, in the audit and the task view, each role's route and source
(`models_by_workload:<slot>` or `main_model_fallback`), plus the coder's workload,
complexity and reasons. Provider and model names are recorded; credentials never are.

## Android approvals

The phone uses the existing pairing listener (`gateway/mobile_preview.py`). The new route
`POST /meu/coding` (`gateway/mobile_coding.py`) is mounted next to projects and transfers,
behind the same TLS pinning, interface check and bearer guard.

**One authority.** The route and the desktop RPC both resolve
`meu_coding/service_registry.py::service_for_home(profile_home)`, inside the profile's
runtime scope. They therefore share one `CodingTaskService`, and its approval objects.

**Phone operations:**
- `list` and `get`: sanitized view;
- `diff`: one file's full proposed or actual diff, capped at 2,000 lines;
- `decide`: approve or reject, naming the approval id and fingerprint;
- `keep` and `reject` (result).

There is no start, commit, integrate, push or merge.

**Identity.** Decisions are attributed to `phone-<pairing device id>` from the pairing
itself. Any `device`, `source` or `approver` field in the body is ignored.

**Sanitized views:**
- the project name, not its path;
- the worktree branch, not its path;
- risk, files, plan summary and expected tests;
- the fingerprint;
- per-file diff summaries, capped at 40 lines per file and 200 lines in total, expandable
  per file;
- after execution: actual diff summary, tests and Reviewer verdict.

**Android UI** (`apps/android/.../MainActivity.java`):
- **Coding approvals** list, using the existing visual language;
- task screen with stage, PC status, risk, files, plan, expected tests and short
  fingerprint;
- the proposed and actual diff summaries, with **Show full diff** per file;
- **Approve** and **Reject**, **Keep** and **Reject result**, and **View details** (full
  fingerprint, approval id, decisions with their source);
- auto-refresh every 3 s while the PC is working.

`MeuClient` now surfaces the PC's refusal reason (HTTP 409 `reason`), so stale or
duplicate decisions explain themselves.

Mobile commit is **not** offered: the phone keeps or rejects, and the desktop commits and
integrates.

## Cross-device behaviour

- **Start on the desktop, approve on the phone, return to the desktop.** It is the same
  task with the same timestamps. The desktop sees the phone's decision on its next read
  (about 0.1 ms; there is no copy to synchronise).
- **Exactly one decision executes.** Whichever device decides first consumes the approval
  under the task lock. The other device, a replay or a stale screen gets "This approval was
  already used or the task has moved on." A wrong id, a wrong fingerprint or another
  proposal with the same title gets "Proposal changed after approval — approval required
  again."
- **Repairs need a new approval.** A repaired proposal carries a new approval id and
  fingerprint. The Phase 3 binding also covers the worktree identity (repository root,
  branch, base commit), so a moved HEAD or an edited target blocks execution.
- **Opening a task calls no model.** Opening a task on another device reads the stored
  snapshot and makes no Architect, Coder or Reviewer call.

## Offline behaviour

- **Phone offline.** The PC continues under the normal rules. A pending approval stays
  pending; nothing is decided for the phone. On reconnect, the phone reads the current
  state, including decisions made on the PC, with their source.
- **PC unreachable.** The phone keeps the last list it received and shows "PC offline or
  unreachable — nothing runs from here until it is back. Pending approvals stay pending on
  the PC." with the last sync time. It never pretends that worktree execution is available.

## Recovery after restart

`meu_coding/task_recovery.py` maps each stored stage explicitly:

| Stored | Recovered | Allowed |
|---|---|---|
| awaiting_approval | awaiting_approval, **expired** | Reject only (the approval object is gone) |
| executing / testing / reviewing_diff / integrating | **interrupted** | Reject only (existing safe cleanup) |
| analyzing … reviewing | failed | none (start again) |
| awaiting_keep_reject / ready_to_commit / committed / integrated | same | Keep, commit or integrate, re-verified against the reviewed-diff digest and git state |
| integration_preview | committed | preview again |

Nothing mutating resumes on its own.

## Audit

The Phase 4 audit is extended with:

- the decision source per decision (desktop or mobile, with the device);
- model routing per role, with the coder's complexity and reasons;
- the result record;
- the integration preview summary and its outcome: branch, commit, target head, final
  files, checks, final review, patch-changed flag;
- target drift;
- integration and cancel decisions;
- PR preview metadata.

Tokens, diffs, file contents and secrets are never stored. The secret-name guard from
Phase 4 still applies.

## Security boundaries

- **Approvals.** Approval integrity is unchanged: exact id and fingerprint, single use, the
  Phase 3 binding, and a new approval after every repair.
- **Integration approval.** It is separate from execution approval. It names the preview
  token and needs a confirmation. A target that moved after the preview blocks.
- **Isolation.** Integration runs only in a new worktree, through the existing worktree
  system. A cherry-pick conflict is aborted inside that worktree. The target branch and the
  parent checkout are never written.
- **Git.** Calls use MEU's hardened, bounded runner (no hooks, pager, editor, credential
  helpers or attribute drivers). There is no `push`, `fetch`, `merge` into the target,
  `rebase`, `reset --hard`, `clean`, `checkout` or `--force` anywhere.
- **Phone surface.** Pairing identity, a narrow operation set, sanitized views and no host
  paths; spoofed body fields are ignored.
- **Routing.** It never bypasses approvals and stores no secrets.

## Known limitations

- **Android validation.** The changed Android sources (`MainActivity.java`, `MeuClient.java`,
  `MeuRelay.java`) were compiled together with the rest of the app. The build used the
  existing JDK 17 (`javac --release 8`), `android-35/android.jar` and the ZXing jar from
  the official `apps/android/build-preview.sh`. `MeuEndpointTest` and `MeuPairingTest` pass
  through that script. Two steps were **not** done:
  - **The preview APK was not built.** The official script requires Android build-tools
    35.0.0, and the existing SDK has 36.0.0 only. Nothing was installed or changed to work
    around it.
  - **No emulator or device smoke test was run.** No emulator was installed and no device
    was connected. Approving on a phone, seeing the result, Keep/Reject, a stale approval
    being refused, and reconnecting still need a real device.

  The server side is fully tested, including the real aiohttp route and a desktop RPC plus
  phone route flow.
- **The Java app is the legacy companion.** `apps/android` is the legacy Java companion. The
  current private Flutter Meu Mobile app is outside this repository and needs its own client
  for `POST /meu/coding`.
- **Integration needs the parent checkout on the target branch head.** The worktree system
  creates worktrees from the checkout's HEAD; otherwise integration blocks with an
  explanation.
- **Branch naming.** Integration branches follow the existing `hermes-subagent/` naming,
  not `meu/integrate/<id>`.
- **Restored tasks.** Integration of a restored task skips the model review of the final
  diff, because the live session is gone. The rule-based checks still run.
- **No remote actions.** Push, remote PR creation and merge are Phase 6.
- **Phone refresh.** The phone polls every 3 s while the PC works; there are no push
  notifications.
