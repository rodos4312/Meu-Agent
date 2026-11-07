# Shared project memory and cleanup ideas — 2026-11-07

Static source review only. No external skill/package/service was installed,
executed or copied into Meu, and no memory or approval setting was changed.
The grouped release remains separate from these research proposals.

## Shared memory: the useful part

[pedicelmarketing/hermes-multi-agent](https://github.com/pedicelmarketing/hermes-multi-agent/tree/f2ac1c91851140f65c9df139a2667955ae04fff5)
is deployment glue around Paperclip, Hermes and MemOS, with separate worker
profiles. Its inspected MemOS handlers use authenticated store/search requests
and configured user/cube identity. The model does not supply that identity.
This is a service-backed knowledge layer, not merely a shared Markdown file.

The README's layered architecture is not the final word: the
[April 28 decision](https://github.com/pedicelmarketing/hermes-multi-agent/blob/f2ac1c91851140f65c9df139a2667955ae04fff5/memos-setup/learnings/2026-04-28-collapse-to-single-tier-memos.md)
records removal of an unused holographic tier and retention of MemOS v1 after
abandoning a v2 migration. The server depends on Qdrant/Neo4j/SQLite. Its notes
also describe an LLM extraction cost for fine-mode writes. These are the
authors' deployment observations, not a performance measurement made here.

### Meu already has

- Local, profile-owned project notes, revision history and project identity
  that survives a real folder move without merging independent copies.
- Parent-selected note IDs passed into each helper's initial context; the
  checkpoint records the exact facts used, and stale notes refuse dispatch.
- Verified prerequisite reports passed into later tasks, and attempt/file-hash
  bindings for independent review. This is controlled handoff, not a live
  unrestricted shared memory bus.

### Proposed next improvement, not implemented

Build on that local project store/checkpoint rather than introducing the whole
external deployment stack. Record small findings with source task/attempt,
artifact version, status (proposed/verified/superseded) and actual evidence.
Keep separate facts when helpers disagree; the parent resolves or leaves the
disagreement visible instead of silently overwriting another helper's work.
Use selective retrieval with a bounded context budget. Preserve the current
conversation prefix; newly written facts do not rewrite earlier prompts.

Only the owning project/profile shares this information. Workers should not
read each other's terminals or receive all transcripts. The local file stays
on the owner device; selected facts still enter requests to the chosen LLM.
Routine memory/skill approval defaults stay unchanged. This proposal needs
isolation, concurrent-write, stale-version, restart and token-budget tests
before inclusion in an implementation or release.

## Focused cleanup review

[Sahil-SS9/hermes-simplify-swarm](https://github.com/Sahil-SS9/hermes-simplify-swarm/tree/0855c033419e5e1890251476cce73dd60cc27f89)
provides a skill and specialist prompts: Hygiene, Clarity and Correctness
inspect a diff read-only and return JSON. The orchestrator consolidates and
deduplicates findings; a fourth independently spawned agent is not required.
This is independent analysis followed by consolidation, not necessarily debate.

Useful ideas are narrow diff scope, concrete file/evidence references, checking
the caller and callee before accepting a finding, and testing each repair.
Risk labels and agreement are not proof that deletion is safe. The inspected
skill has a default approval stop and a broad working-tree rollback example;
neither should be transplanted unchanged into Meu. A future optional cleanup
mode should retain existing authorization, isolate its own edits and fit the
native two-child budget. No permanent swarm is needed for ordinary requests.

## Rust state-machine reference

[m0at/hermes-lite](https://github.com/m0at/hermes-lite/tree/f04a8177698d7c0aba3cfe99a3308b2ef541838e)
contains a Rust/PyO3 loop machine and session database, a Ratatui frontend and
JSON pipe messages to Python agents. Python inference/tool code remains;
the [original discussion](https://github.com/NousResearch/hermes-agent/issues/730)
also describes optional Rust fallbacks. It is not evidence that rewriting
Meu's Windows/Android backends in Rust would improve their measured bottleneck.

Keep the architectural ideas: explicit states, bounded retries, process
ownership and structured UI events. Meu already has native state/progress and
recovery authorities; preserve those instead of introducing another runtime.
No Windows/Android compatibility or benchmark was exercised for this project.
