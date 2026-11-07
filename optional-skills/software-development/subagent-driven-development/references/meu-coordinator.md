# SDD with Meu Coordinator

Use this adapter when `coordinate_project` is available in a new Meu Coordinator
session. It reuses native delegation, project checkpoints and existing approval
settings. It does not install another runtime or choose another provider.

## Choose the amount of review

- Complete a small direct request yourself and check it. Do not create a project
  merely to answer a question or perform a bounded mechanical edit.
- In a project, `review_policy: auto` is the default. A `standard` or `complex`
  task with nonempty `write_paths` receives two generated reviewer tasks.
- `routine` mechanical work and read-only research receive no automatic extra
  reviewers. Judge the work by meaning; never mark substantial implementation
  routine just to avoid its checks.
- For an explicit SDD experiment on any task, set `review_policy: two_stage`.
  This requires the two checks even for a small or read-only assignment. Use it
  deliberately; it adds at least two helper runs, using the session provider.

## Create the plan once

Call `coordinate_project(action="create", project=<stable id>, root=<existing
absolute directory>, tasks=[...])`. Each authored task supplies `id`, `goal`,
`workload`, `acceptance`, `parallel_safe`, `write_paths`, and optional
`depends_on`, `tool_access`, `context`, `review_policy`.

For example, a substantial task might declare:

```json
{
  "id": "implement-import",
  "goal": "Implement task import without dropping valid unusual IDs.",
  "workload": "standard",
  "acceptance": "Import duplicate IDs and an ID named constructor; retain exactly one of each valid ID.",
  "parallel_safe": true,
  "write_paths": ["app.js", "tests/import.test.js"],
  "review_policy": "auto"
}
```

Do not invent the generated review IDs. Read them and their dependencies from
the tool result. The coordinator adds requirements, then quality, and makes
downstream deliverables wait for both. Separate overlapping edits. Give each
helper the full relevant requirement, files and concrete expected observations.
For meaningful behavior changes, request a failing regression test followed by
the implementation and passing check, using the project's actual test command.
Do not request blanket commits, publication or unrelated changes.

## Run and accept in order

1. `run` starts ready work through native delegation. Read the saved status after
   completion or reconnect. Completion is `needs_review`, never acceptance.
2. The parent inspects the deliverable and executes its acceptance checks with
   its normal tools. `verify` records the exact attempt, actual evidence and
   artifact paths. This unlocks the requirements reviewer.
3. The requirements reviewer inspects the original requirements and actual
   deliverable. It returns `pass`, `needs_fix` or `inconclusive`, plus `check`
   and `observed`. Parent verification of a valid pass unlocks quality.
4. The quality reviewer inspects correctness, edge cases, maintainability,
   security and relevant tests. Parent verification of its valid pass unlocks
   downstream work. Both reviewers are read-only; the parent owns executable
   validation and must report missing evidence honestly.
5. Finish with appropriate integration checks. A complete graph records the
   parent's acceptance and file hashes; it does not prove that every claimed
   test actually ran. Include the exact returned project folder link.

## Revision, interruption and limits

Reproduce a `needs_fix` finding before calling `request_fix` with its review
task, exact attempt and evidence. Repair stays within the original write scope.
Both stage reviews run again for the repaired version; unrelated accepted work
stays intact. Changed artifacts invalidate old review receipts. Attempts remain
capped at three per task/reviewer; report unresolved work when exhausted.

Use `inconclusive` for missing evidence. Do not manufacture a pass or force a
repair from an inconclusive report. Reconcile interrupted work before explicit
`retry`. Never recreate the project to evade its attempt budget.

Existing saved graphs keep their old semantics when reopened; they are not
silently expanded. Start a new plan for an intentional SDD trial. Routine review
and skill/memory actions do not introduce new user approval prompts.
