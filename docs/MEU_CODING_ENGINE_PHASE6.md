# Meu Coding Engine — Phase 6: controlled remote GitHub operations

> **Historical implementation notes.** This records how the phase was built and why. The current
> system is described in [MEU_CODING_ENGINE.md](MEU_CODING_ENGINE.md); names here may have moved or
> been removed since.

Phase 6 takes a validated integration (Phase 5) to GitHub, under explicit control:

- detect the remote and whether it can be used;
- push the integration branch;
- create a pull request;
- monitor the PR's checks and reviews;
- merge the PR.

Each remote mutation is its own preview, its own fingerprint and its own single-use approval:

> push approval ≠ PR approval ≠ merge approval.

Nothing runs automatically. There is no force push and no branch deletion. Code is never edited from PR comments, and an AI is never treated as an approver.

**Validation was local only.** It used a temporary bare git repository as the remote and a fake GitHub API (`FakeGitHub`, tests only). No real GitHub repository, branch, PR or merge was touched, because the project rule is to never touch GitHub. The real REST adapter is implemented but was not exercised against github.com (see *Known limitations*).

The 97 known failures of the full desktop test suite are pre-existing and were not touched.

## Modules

| File | Topic |
|---|---|
| `meu_coding/remote_refs.py` | Remote detection, URL-substitution refusal, strict remote/branch/SHA validation, `ls-remote` reads |
| `meu_coding/github_adapter.py` | `GitHubApi` protocol and the minimal `RestGitHub` client on MEU's credential ladder |
| `meu_coding/remote_ops.py` | Push / PR / merge previews, fingerprints and re-verified execution; PR status summaries |
| `meu_coding/task_remote.py` | `RemoteMixin` of `CodingTaskService`: previews, the approval ledger, audit events, refresh, feedback → new task |
| `tui_gateway/methods_coding.py`, `contracts/coding.py` | `coding.remote.*` RPC |
| `gateway/mobile_coding.py` | Phone view and approval of remote operations (`remote_approve`, `remote_refresh`) |
| desktop `meu-coding/remote.tsx`, `remote-model.ts`, `parts.tsx` | REMOTE section of the task page |
| `apps/android/.../MainActivity.java` | Remote section on the legacy Java companion |

## Remote capability detection

`detect_remote(repo)` never invents or configures a remote. It reports `available=false` with a plain reason in any of these cases:

| Situation | Message |
|---|---|
| no remote | "No git remote is configured for this repository — remote actions are unavailable." |
| several remotes, none named `origin` | refused (ambiguous) |
| several URLs, or push URL ≠ fetch URL, or an `insteadOf`/`pushurl` rewrite (checked against `git remote get-url --push`) | refused as **URL substitution** |
| URL is not `https://github.com/o/r`, `git@github.com:o/r` or `ssh://git@github.com/o/r` | "not a GitHub repository". Look-alike hosts, userinfo URLs, `http://` and dot-only names are rejected. |
| no credentials | "No GitHub credentials are available to Meu — remote actions stay disabled." |
| credentials without push permission | "These credentials cannot push to the repository." |
| GitHub unreachable | disabled, with the error type |

When the remote is usable, detection also records:
- `default_branch`;
- `permissions.push`;
- the merge methods the repository allows (`allow_merge_commit` / `allow_squash_merge` / `allow_rebase_merge`).

**Credentials** use the existing ladder in `hermes_cli/github_api.py::github_token`: `GITHUB_TOKEN`, then `GH_TOKEN`, then `gh auth token`. Meu has no second GitHub client stack and never prompts for, stores or prints a token.
- The token exists only in the `Authorization` header of a request to `https://api.github.com`.
- Error messages are rebuilt from GitHub's `message` field. A test proves the token is absent from errors.
- Git itself runs with MEU's non-interactive env: no credential helper, no askpass, BatchMode ssh. This is the same env as the existing desktop push in `hermes_cli/web_git.py`.

## Push

**Allowed command, exactly:**

```
git push --porcelain --no-verify <validated remote> refs/heads/<integration-branch>:refs/heads/<integration-branch>
```

The command never includes `--force`, `--force-with-lease`, `--mirror`, `--all`, `--tags`, a `+` refspec or a deletion.

**What can be pushed:**
- Only `hermes-subagent/…` integration branches.
- Never `main`, `master`, `trunk`, `develop`, `production`, `release`, the repository's default branch or the task's target branch.

**Name validation.** Every name passes an allowlist and then `git check-ref-format`. The allowlist rejects `..`, `@{`, `//`, `.lock`, `~ ^ : ? * [ \`, spaces, a leading `-` and a trailing `/` or `.`.

**Push preview** (`remote_preview(task, "push")`, read-only) contains:
- repository identity;
- remote name and URL;
- source branch and commit;
- destination branch;
- whether the remote branch exists, and its SHA (= expected remote SHA);
- the new SHA and the exact refspec;
- `force: FORBIDDEN`;
- changed files, tests, Reviewer verdict, risk and target branch.

If the remote branch has commits the local one lacks, `force_required=true` and the preview is **blocked**, because a force push is forbidden.

**Fingerprint.** It is sha256 over: repository, remote, remote URL, source branch, source commit, destination branch, expected remote SHA, new SHA, refspec.

**Execution** (`remote_approve(task, "push", fingerprint, confirmed=True)`):
1. Rebuild the preview from live state. If anything moved, the fingerprint differs and the push is refused.
2. Push, fast-forward only.
3. `ls-remote` must report the new SHA; otherwise the task is **BLOCKED**.

## Pull request

**PR preview** (only after a push, read-only) contains:
- repository;
- head branch and pushed SHA (re-read with `ls-remote`; it must still match);
- base branch and its remote SHA;
- title (whitespace-collapsed, at most 200 characters);
- body (at most 20,000 characters, NUL removed) and its sha256;
- commits, files, tests, risk and limitations.

The default text is the Phase 5 local PR preview, if the user prepared one, else one built from the task.

**Editing.** Editing the title or body and previewing again produces a new fingerprint, which invalidates the old one.

**Creation**, after its own approval:
1. Re-check the head SHA.
2. Refuse if an open PR for the same head and base exists. No duplicate PR is ever created.
3. Call `POST /pulls`.
4. Verify that GitHub's head SHA is the approved one.

It records number, URL, id, head SHA, `created_at`, author and state. Title and body are sent only as JSON values; nothing in them is executed or interpreted.

## Monitoring

`remote_refresh` runs on demand only; there is no polling. It reads:
- state, draft, merged;
- `mergeable` / `mergeable_state`;
- the commit status and check runs (passing / pending / failing / none);
- reviews: the latest per reviewer, counting approvals and changes requested;
- **head drift** (head ≠ the approved PR head);
- **target drift** (base SHA ≠ the base SHA at PR preview).

## Merge

**Merge preview** (only after a PR exists, read-only). Its status is one of:

| Status | When |
|---|---|
| `clean` | open, not draft, head = reviewed head, checks passing or none, no changes requested, method allowed, Meu Reviewer PASS, target unchanged |
| `revalidation_required` | the target branch moved since review |
| `conflict` | GitHub reports `mergeable=false` or `dirty` |
| `blocked` | any other reason, each listed |

Only methods the repository allows are offered (`allowed_methods`).

**Fingerprint.** It binds repository, PR number, head SHA, target SHA and method.

**Execution** (second, separate approval):
1. Rebuild the preview. Any change refuses the merge.
2. Call `PUT /pulls/{n}/merge` with GitHub's own `sha` guard set to the approved head.
3. Re-read the PR, which must report `merged`.
4. Read the target branch with `ls-remote` and record `target_verified` (the target head = the merge commit).

No branch is deleted, locally or remotely. Tasks that were pushed cannot be rejected into cleanup; the user closes the PR or deletes the branch on GitHub themselves.

## Approval ledger

- One pending preview per kind (`push`, `pr`, `merge`), held in memory with the task.
- An approval names the kind and the exact fingerprint, and needs `confirmed=true`.
- It is consumed under the task lock **before** anything is sent. A replay, a concurrent duplicate, a stale or foreign fingerprint, the wrong kind or another task's preview are all refused. Four concurrent approvals produce exactly one PR.
- Accepted approval sources are `desktop` (RPC) and `phone-<pairing device id>` (phone route; body fields are ignored). Anything else (`agent`, `model`, `auto`…) is refused. A refused source does not consume the approval. Meu never submits a GitHub review, so it can never approve its own PR.
- After a restart, pending previews are gone; completed facts (push, PR, merge) are restored from the audit.

## Remote states (task view `remote.state`)

`unavailable` (No remote configured) · `not_checked` · `ready_to_push` · `push_preview` (approval required) · `pr_ready` · `pr_preview` · `pr_open` · `checks_running` · `changes_requested` · `approved` · `merge_preview` · `merged` · `blocked`.

## Desktop UI — REMOTE section

The REMOTE section appears for integrated tasks.
- **Check remote** shows the repository and remote, or the reason they are unavailable.
- **Preview push** shows the facts above. **Approve push** needs a checkbox naming the exact refspec.
- **Preview PR** takes an editable title and body; **Create pull request** needs its own checkbox.
- **Refresh PR** shows state, checks, reviews and drift.
- **Preview merge** shows status, reasons, head and target SHAs, method, checks, reviews, Meu Reviewer verdict and risk. **Approve merge** needs a separate checkbox.
- **Cancel** is available on every preview.
- **Review feedback… → Create repair task from PR feedback** works on selected comments.

## Phone

`POST /meu/coding` gains `remote_approve` (kind, 64-hex fingerprint, `confirmed: true`) and `remote_refresh`. The phone cannot create previews; the PC prepares each one.

**The mobile view shows:**
- repository identity;
- refs and short SHAs;
- force status, PR title, checks, reviews, merge status and reasons, risk and files;
- the fingerprint.

It never shows remote URLs or host paths. A task waiting for a remote approval is labelled **Needs remote approval**. Approvals are attributed to `phone-<device>`, following the Phase 5 cross-device rules: one authority, first decision wins, others are refused.

**Android** (legacy Java companion) has a Remote section with the same facts. Each approve button opens a confirmation dialog that repeats the exact operation and fingerprint.

## PR feedback → repair task

`remote_feedback` lists the PR's review comments: id, path, line, author, body.

`remote_repair_task(ids)` starts a **new** coding task from 1–20 selected comments. That task is planned, reviewed and needs its own approval. Code is never edited from comments. Comment text is data in the task description; it cannot trigger remote actions.

## Audit

The task's audit gains `remote`:
- detection info;
- the previews;
- the push result (remote SHA, refspec, expected SHA, approver);
- the PR (number, URL, head SHA, author, approver);
- the last PR status;
- the merge (merge SHA, method, target before and after, `target_verified`, approver);
- the block reason;
- an event log: `*_preview`, `*_approved`, `pushed`, `pr_created`, `pr_refreshed`, `merged`, `*_blocked`, `*_cancel`, `*_error`, `repair_task_created`.

It never stores tokens, credentials or pending approval objects. The Phase 4 secret-name guard still applies.

## Security boundaries

- **Approvals.** No automatic push, PR or merge. Each mutation needs its own fingerprinted, confirmed, single-use approval, and is re-verified against live refs right before it runs.
- **Forbidden git operations.** Force, `--force-with-lease`, `--mirror`, `--all`, `--tags`, `+` refspecs and deletions. Main, master, default or target branches are never pushed to.
- **Injection.** Option, refspec and revision injection are refused by validation before git sees the name. URL substitution disables the remote.
- **Credentials.** Never requested in chat or UI, never printed, never logged, never stored.
- **Branches.** None is ever deleted.
- **Timers.** No polling. Remote calls happen only on a user action.

## Measurements

Local bare remote and fake GitHub on Windows (median of 5). Times are dominated by git process start-up. Real GitHub adds network round trips.

| Step | Median |
|---|---|
| remote detect | 461 ms |
| push preview | 881 ms |
| push execute + verify | 1,703 ms |
| PR preview | 1,351 ms |
| PR create | 854 ms |
| PR refresh | 625 ms |
| merge preview | 627 ms |
| task view build | < 0.1 ms |

## Known limitations

- **Not validated against real GitHub.** The project rule is to never touch GitHub, so `RestGitHub` was exercised only through its error and credential path (with a stubbed `urlopen`). The push, PR, refresh and merge logic ran against a local bare repository and `FakeGitHub`. Before real use, test on an isolated repository the user owns.
- **The REMOTE UI has not passed a live Electron smoke test.** It is verified by typecheck, build, eslint, prettier and the `remote-model` unit tests. The backend it calls is covered by the RPC, flow and attack tests.
- **Branch protection** is not used to block, only reported (`branch_protection` returns None when not visible). GitHub still enforces it on merge, and its refusal is reported, never assumed.
- **Merge methods.** The UI offers `squash` by default; the backend accepts only methods the repository allows.
- **GitHub only.** GitLab and other hosts are reported as unavailable.
- **Android.**
  - The Java sources compile (`javac --release 8` against `android-35/android.jar` and ZXing).
  - `MeuEndpointTest` and `MeuPairingTest` pass through `apps/android/build-preview.sh`.
  - The APK is still **not built**: build-tools 35.0.0 is missing and only 36.0.0 is installed. Nothing was installed.
  - There is no emulator and no device, so the phone UI was not exercised on hardware.
- **Pending previews are memory-only.** A restart drops them on purpose; the push, PR or merge preview has to be created again before approval.
