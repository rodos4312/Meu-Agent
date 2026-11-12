# Meu Coding Engine — Phase 7: intelligence and controlled autonomy

Phase 7 makes the Coding Engine better at finding the right code and at planning larger goals, without
giving it any new authority.

- **Semantic embeddings** are an *extra*, optional relevance signal. They are not a replacement:
  - the Phase 1 dependency/symbol graph stays the single graph;
  - exact file/symbol matches and structural impact analysis stay authoritative.
- **One change path.** File changes update the repo index, graph, relevance index and semantic
  chunks in a single step; there are no separate watchers.
- **Autonomous Planner.** Broad goals become roadmaps of milestones, and every milestone needs its
  own user approval. There is no "run until finished".
- **Project memory.** Curated coding knowledge lives in MEU's existing project memory. Notes are
  saved only when the user accepts them, and stale notes are detected.
- **Smarter routing** on top of *Models by workload*, with controlled escalation; the Reviewer is
  never downgraded.
- **Optional delegation.** Read-only investigations and patch candidates, under strict policy.
- **Observability.** Every result exposes its score components ("Why these files?"), the
  intelligence metrics and the route reasons.

The Phase 2–6 approval, execution, worktree, PR and merge flows are unchanged and are not bypassed.
The 97 known desktop failures are untouched; they are deferred to Phase 8 (see
`docs/MEU_DEFERRED_WORK.md`).

## Semantic architecture

| Module | Role |
|---|---|
| `meu_coding/embeddings.py` | `EmbeddingProvider` protocol, `EmbeddingVector`, `ProviderIdentity`; the local and MEU-API providers; resolution from config |
| `meu_coding/semantic_index.py` | `SemanticChunk`, chunking, exclusions, `SemanticIndex` (SQLite, project-scoped), `SemanticLayer` (availability facade) |
| `meu_coding/semantic_search.py` | `semantic_search(index, query, top_k)` → `SemanticHit`s; `layer_search` never raises and never fakes |
| `meu_coding/semantic_setup.py` | `build_intelligence(root)`: the Phase 1 `RepositoryIntelligence` with the layer attached |

### Provider behaviour

MEU had no embedding provider before Phase 7. The choice comes from the profile's `config.yaml`:

```yaml
coding_engine:
  semantic:
    provider: off        # off (default) | local | <any MEU provider name>
    model: ""            # embedding model, required for a provider
    dimension: 256       # local provider only
    include_tests: false # tests are already linked structurally
```

| Setting | Behaviour |
|---|---|
| `off` (default) | Semantic search is unavailable and the engine works exactly as in Phase 6 (structural intelligence). Nothing is required. |
| `local` | `LocalSubwordEmbeddings`: deterministic signed feature hashing over identifier sub-words (camelCase/snake_case split, light stemming), word pairs and character trigrams. No model, no download, no network. It is a **lexical-semantic** signal (it links `reconnect` / `reconnection` / `ReconnectState`), not a neural model, and the UI labels it "local sub-word similarity (no model)". |
| `<provider>` + `model` | `MeuApiEmbeddings`: an OpenAI-compatible `/embeddings` call through MEU's own client resolver, `agent.auxiliary_client.resolve_provider_client`. That means MEU's credentials, base URLs, proxies and local OpenAI-compatible runtimes; there is no second secret store. Missing credentials or an endpoint without embeddings ⇒ the layer is **unavailable**, with the reason shown. |

If the provider fails at any point, the layer marks itself unavailable, ranking falls back to
structural signals and the coding task continues. There are no fake results.

### Chunks and storage

- **Chunk boundaries** are the definitions the Phase 1 extractor already found: function, class,
  method, interface, struct, enum, trait, type. Code before the first definition becomes a
  `module` chunk. Files without definitions (docs, config) become 40-line sections. Every chunk
  is capped at 80 lines, so whole files are never embedded blindly.
- **Chunk metadata:**
  - project identity, path, symbol, container, kind, language;
  - start/end line;
  - content hash and source hash;
  - provider key (provider, model, version, dimension) and chunking version.
- **Storage** is one SQLite file per project in `<HERMES_HOME>/coding_semantic/<project-digest>.sqlite`,
  holding metadata plus a float16 vector. **No source text is stored.** It is local, needs no
  server, and the store is rebuilt automatically on a schema change.

### Never embedded

- Protected paths (`.git/`, `.env*`, virtualenvs).
- Credential and key files (`auth.json`, `credentials*`, `id_rsa*`, `*.pem`, `*.key`, `*.p12`,
  `*.jks`, `*.keystore`, `.netrc`, `.npmrc`, `.pypirc`, `.git-credentials`, token stores),
  credential directories (`.ssh`, `.gnupg`, `.aws`, `.kube`, `mcp-tokens`, `pairing`, `secrets`)
  and binaries.
- Any chunk that MEU's own redactor (`agent.redact.redact_sensitive_text`, forced) would alter.
- Tests, unless `include_tests` is set.

## Incremental embeddings

`RepositoryIntelligence.refresh_changed_files` stays the **one** change detector (size and mtime,
as in Phase 1). Its single per-file path now runs:

1. repo index
2. graph
3. relevance index
4. semantic chunks: `SemanticLayer.update_files` / `remove_file`
5. embedding of new chunks only
6. consistency, through the content-hash identity

`analyze_repository` ends with `SemanticLayer.sync`.

| Case | Result |
|---|---|
| unchanged file | skipped by metadata, **not even read** |
| touched, same content | metadata updated, nothing re-embedded |
| one function changed | only that chunk re-embedded; others kept |
| deleted file | its chunks removed |
| renamed file | vectors reused by content hash where the chunk text is identical (the chunk header names the path, so a moved chunk costs one embedding) |
| provider, model, version, dimension or chunking change | affected chunks recomputed; old vectors ignored |

## Hybrid relevance

The Phase 1 `RelevanceEngine` is extended, not replaced. Every signal now records a **component**,
and `RankedItem.components` / `component_totals()` expose them:

```
final_score = structural_graph + symbol_match + path_file_match + dependency_proximity
            + test_relation + recent_change + semantic_embedding + memory
```

| Signal | Points |
|---|---|
| explicit file | 100 |
| exact symbol | 45 |
| direct dependency | 18 |
| reverse dependency | 14 |
| filename | 25 |
| keyword overlap | ≤ 15 |
| related test | 12 |
| recent change | 8 |
| **semantic similarity** | **≤ 16**, linear above similarity 0.25 |
| **memory note** | **5** |

### False-positive protection

- An exact file or symbol mention dominates, and a direct dependency outranks any semantic match.
- Semantic and memory signals never seed graph signals.
- Semantic and memory signals never apply to protected or security-sensitive paths.
- A file found **only** by semantic similarity or memory is `discovery_only`:
  - it may be read as context;
  - the Architect never chooses it as an edit target (`_choose_files`);
  - `validate_plan` refuses a plan that edits it unless the user named it.

Embeddings help discovery; they never authorise anything.

## Autonomous Planner

`meu_coding/autonomous_planner.py` (plan-only) and `meu_coding/task_roadmap.py` (user control)
implement this flow:

```
Goal → read-only planning (route coding.planner)
     → roadmap: milestones in a DAG (no cycles; unknown or self dependencies refused; ≤ 12)
     → user reviews → user approves ONE ready milestone (id + fingerprint + revision + confirm)
     → a normal coding task (Architect → Coder → Reviewer → its own approval → worktree …)
     → the task outcome sets the milestone status
     → the planner PROPOSES a revision (keep / reorder / split / add / remove)
     → the user accepts or declines it → the next milestone needs its own approval
```

**Milestone fields:** id, title, objective, depends_on, expected_areas, acceptance criteria,
tests, risk, complexity, kind, status, task_id, outcome.

**Statuses:** PLANNED → READY (dependencies DONE) → APPROVED → IN_PROGRESS → DONE, BLOCKED or
REJECTED. Milestone status is derived from the linked task:
- ready to commit, committed or integrated ⇒ DONE;
- blocked, failed, interrupted, rejected or an expired approval ⇒ BLOCKED.

**Planner context:**
- the ranked repository areas, from the cached index (changed files only, never a rescan per
  milestone);
- current project memory; stale notes are listed as ignored;
- deferred work, which the planner is told not to plan unless the goal names it.

**What the planner cannot do:** approve its own roadmap or a milestone, execute, edit files, push,
open a PR, merge or install anything. It has no handle to any of these. Approval sources are the
desktop and paired phones only; `planner`, `agent`, `model` and `auto` are refused.

**Revisions:**
- material changes are always shown, with new milestones and new areas listed as scope
  expansion;
- APPROVED, IN_PROGRESS, DONE and REJECTED milestones cannot be changed or removed;
- a revision proposed for an older roadmap revision is refused as out of date.

**User controls:** approve a milestone, reject a milestone, edit the roadmap (a new revision; locked
milestones are protected), pause/resume, and plan again. There is no approve-all and no bulk
approval. Only one milestone of a roadmap runs at a time.

**Milestone task scope.** An expected area that is an existing file was shown and approved with the
milestone, so it becomes a named file of the task. Directories stay discovery hints.

**Persistence.** Roadmaps are JSON files (MEU's atomic writer) in `<HERMES_HOME>/coding_roadmaps/`.
- A restart resumes nothing mutating: a milestone whose task was interrupted, or whose approval
  expired, shows as BLOCKED.
- Interrupted planning, which is read-only, is marked `planning_interrupted` and can be planned
  again.

## Project memory

`meu_coding/coding_memory.py` stores notes in MEU's **existing** project memory: `PROJECT.md`,
through `tools.memory_tool.load_on_disk_store(project_cwd=…)` and `MemoryStore.add("project", …)`.
There is no second database, and MEU's limits, locking, drift checks and injection/exfiltration
scan all apply.

**Entry format:**

```
[meu-coding:KNOWN_BUG] <note> | files: a.py, b.py | symbols: f, C | source: task 1a2b3c4d
```

**Categories:** ARCHITECTURE_DECISION, PROJECT_CONVENTION, KNOWN_BUG, FIX_HISTORY, TEST_KNOWLEDGE,
RISK_NOTE, USER_PREFERENCE, DEFERRED_WORK, KNOWN_LIMITATION.

**Saving:**
- Nothing is saved automatically.
- A finished task proposes candidates (note, category, source task, confidence, why it matters).
- A candidate is saved only when the user accepts it, and only if it passes these checks:
  - category known, confidence ≥ 0.6, 15–300 characters;
  - not transient (log lines, timestamps, temp paths, "this run");
  - repository-relative file paths;
  - nothing the redactor or MEU's memory scanner flags.

**Retrieval** happens before planning (Architect and Planner):
- Notes that mention the query, plus always-relevant categories (deferred work, limitations,
  preferences, conventions).
- Each note is checked against the current repository. A missing file or symbol ⇒ **stale**:
  recorded as ignored and never used. The repository wins.
- Current notes become `memory` discovery hints for their files.

**Deferred work** is also read from the versioned register `docs/MEU_DEFERRED_WORK.md`
(`- [DEFERRED_WORK] …` lines), so the 97 pre-existing desktop failures are visible to the
planner without relying on anyone's personal memory.

## Model routing

`routing_policy.py` extends Models by workload with:
- `coding.planner` (complex slot);
- `coding.semantic`, which is the embedding provider setting, not a chat slot.

`decide_coder_workload(RoutingSignals)` is deterministic:

| Signal | Route |
|---|---|
| high risk (security/config file, high-risk plan, ≥ 25 dependents) | strong from the start |
| complex plan, context > 48,000 characters, any repair, analysis/architecture/design/migration/security milestone | strong |
| simple route failed twice | escalated to strong (`escalated: true`) |
| otherwise | `coding.simple` |

The Coder retries a failing simple route once, then escalates. The Reviewer is always `coding.review`
and never downgraded, and high-risk changes are marked as requiring strong review. Correctness and
risk outrank cost. Every decision and its reasons are recorded in the task's audit `routing`
(`coder_used`: workload, reasons, escalated, context size, simple failures).

## Delegation

`meu_coding/delegation.py`:

- **Kinds:** investigate tests, inspect a subsystem, compare two options, read-only research, a
  patch candidate.
- **Never delegable:** approve, push, create PR, merge, commit, install, write the parent checkout.
- **Concurrency:** parallel only for independent requests on disjoint files, at most 2 at once.
  `FileLeases` refuses overlapping files.
- **Read-only investigations** run in-process on the cached index (dependencies, dependants,
  related tests, ranked options). They hold no file, git or approval handle.
- **Patch candidates** are ordinary coding tasks: isolated worktree, Reviewer, explicit user
  approval.

LLM subagents through `delegate_task` are **not** used. Their tool scope is decided by the
delegation backend, not by the caller, so the Coding Engine could not guarantee a read-only child
(see *Known limitations*).

## Observability and audit

**Task view and audit:**
- `relevance` ("Why these files?"): per file the score, its components, its reasons,
  discovery-only and edit-target flags.
- `intelligence`:
  - ranking evidence counts per component, semantic hits, discovery-only count;
  - semantic status, provider and query latency;
  - memory hits;
  - context items and characters;
  - repairs and milestone.
- `memory`: used and stale-ignored notes, plus accepted candidate ids.
- `roadmap`: the roadmap and milestone the task belongs to.
- `routing`: route and reasons.

Roadmaps keep an event log (created, planned, milestone approved/started/done/blocked, revision
proposed/accepted/declined, paused, edited) with the source of each decision. Contents and secrets
are never stored; the Phase 4 secret-name guard still applies.

## Desktop and mobile

**Desktop.** The Coding page has a **Tasks / Roadmaps** switch.

| Area | What it shows |
|---|---|
| Plan, "Why these files?" (collapsed) | every ranked file with its evidence labels (exact symbol, dependency, related test, semantic similarity, memory, recent change), "context only" for discovery-only files, and "planned edit" |
| Plan, "Intelligence details" (collapsed) | evidence counts, semantic status, memory used and stale memory ignored, context size, repairs, milestone |
| "Remember for this project?" (after a commit or integration) | proposed notes with Accept and Dismiss |
| Roadmaps | goal, milestones (status, dependencies, areas, acceptance, tests, risk, fingerprint), **Approve milestone** (with confirmation), **Reject milestone**, **Edit roadmap**, **Pause/Resume**, **Plan again**, and the planner's revision with **Accept change** / **Keep current roadmap** |

**Mobile.** `POST /meu/coding` gains `roadmap_list`, `roadmap_get`, `milestone_approve` (milestone
id, 64-hex fingerprint, revision, `confirmed: true`) and `milestone_reject`.
- These follow the Phase 5 rules: one authority, attribution to `phone-<device>` from the
  pairing (body fields ignored), single use, and no bulk approval.
- Views carry project names, never host paths.
- A task view names the roadmap and milestone it belongs to.

## Security review

| Risk | Control |
|---|---|
| Secret leakage into the embedding store | sensitive paths and binaries excluded; chunks the redactor would alter skipped; no source text stored; tested |
| Memory storing credentials | redactor and MEU's memory scanner gate every note; tested |
| Semantic search expanding write scope | `discovery_only` items are never edit targets; `validate_plan` refuses them unless named; tested |
| Planner self-approval | approval sources restricted to desktop/phone; the planner has no approve, execute or file handle; tested |
| Milestone approval replay | READY → APPROVED under the roadmap lock before the task starts; fingerprint and revision bound; tested (desktop, RPC, phone) |
| Subagent privilege escalation | forbidden capabilities refused; LLM subagents not used; patch candidates go through normal approval; tested |
| Stale memory poisoning | stale notes detected and ignored; protected and security paths never receive memory points; MEU's injection scan |
| Routing bypassing the Reviewer | the Reviewer is always the strong `coding.review` route; routing never changes what needs approval |
| Embedding provider data leakage | default `off`; `local` sends nothing; an API provider is used only when explicitly configured and never receives excluded files or secret-bearing chunks |

No serious boundary failure was found.

## Performance

Measured on MEU itself (21,786 files) with the `local` provider by
`scripts/meu_coding_semantic_benchmark.py`, on Windows, in pure Python (no NumPy in the
environment).

| Measure | Value |
|---|---|
| Structural index, cold (Phase 1, unchanged) | 24–28 s |
| Initial semantic index (94,872 chunks; tests excluded) | 204 s (first run only) |
| Cached startup, structural + semantic | 24.8–27.1 s (structural alone: 24.3–26.0 s) |
| 1-file semantic refresh | 19–21 ms (unchanged chunks are not re-embedded) |
| 10-file semantic refresh | 75–114 ms |
| Semantic query | median 123–137 ms; the first query of a session takes 3.4 s (it builds the file centroids) |
| Storage | 97 MB (float16) |

A first, unoptimised version (all files including tests, float32, per-file commits, one-stage scan)
measured 998 s for the initial index, 7.2 s per query and 451 MB. The optimisations kept above:
- tests excluded (already structural);
- crc32 feature hashing;
- dimension 256;
- float16 vectors;
- batched commits;
- metadata-only skip of unchanged files;
- two-stage centroid search.

**Relevance on six MEU questions** (recall@10 / MRR):

| Mode | Recall@10 | MRR |
|---|---|---|
| structural only | 0.250 | 0.097 |
| semantic only | 0.333 | 0.139 |
| **hybrid** | **0.333** | **0.375** |

Both exact-structural queries kept their file first. Three of the six questions are not answered
by any mode with the lexical local provider. The semantic weight (relative to the query's best
hit, squared, with an absolute gate, at most 17 points) was chosen on this benchmark.

## Known limitations

- **No neural embedding model yet.** None was available locally and none was installed; every
  benchmark figure above comes from the local fallback embedder.
- **The live API embedding provider is untested against a real endpoint.** `MeuApiEmbeddings` is
  covered only through config resolution and the failure path; calling a real endpoint would have
  sent repository code to a third party.
- **The local fallback embedder is lightweight and lexical** (sub-word feature hashing, no model).
  It links related identifiers, but not true synonyms, so the hybrid gain measured here is a lower
  bound.
- **The first semantic query of a session has extra latency** (about 3.4 s on MEU) while the file
  centroids are initialised; later queries take about 130 ms. The first index of a very large
  repository is also slow in pure Python (204 s for MEU, once). NumPy, when already installed,
  makes search exact and fast; the engine never installs it.
- **No live LLM subagents.** The caller cannot enforce a read-only tool scope through
  `delegate_task`. Read-only investigation runs in-process, and patch candidates are normal coding
  tasks.
- **No live Electron smoke test of the Phase 7 UI** ("Why these files?", Intelligence details,
  memory candidates, Roadmaps). It is verified by typecheck, build, eslint, prettier and Vitest only.
- **The Android roadmap UI is not implemented yet.** The phone API (`roadmap_list`, `roadmap_get`,
  `milestone_approve`, `milestone_reject`) is implemented and tested server-side.
- **The 97 known desktop failures remain deferred** to the Phase 8 hardening
  (`docs/MEU_DEFERRED_WORK.md`). One of the files in that count,
  `electron/plugin-files-spellings.test.ts`, failed only under full-suite load and passes on its own.
- **Planner quality depends on the configured model**; tests use a scripted planner. The planner
  never runs without a configured model.
- **Restarts.** Pending revision proposals survive a restart. Roadmap planning interrupted by a
  restart must be started again (it is read-only).
