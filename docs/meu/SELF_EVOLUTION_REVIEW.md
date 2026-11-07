# Self-evolution review — 2026-11-07

Static review of [NousResearch/hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution)
at revision `0a929e3aa20e15cf04dc7c28492a7d41a5139125`.
This is research for the roadmap, not a validated Meu integration.

## Useful idea and actual scope

The repository proposes generating candidate skill instructions, evaluating
them on training/validation/holdout examples, and retaining measured improvements.
It uses model calls to optimize text. The README lists skill evolution as the
implemented first phase; tool descriptions, system prompts, code evolution and
a continuous improvement pipeline are later phases.

Meu already has persisted skills and background skill review
(`agent/background_review.py`, `tools/skill_manager_tool.py`). A useful addition
would be reproducible comparisons and real acceptance evidence for proposed
skill changes, building on that existing mechanism.

## Findings from the current source

- The [main loop](https://github.com/NousResearch/hermes-agent-self-evolution/blob/0a929e3aa20e15cf04dc7c28492a7d41a5139125/evolution/skills/evolve_skill.py)
  stores the `--run-tests` choice in configuration, but does not call the test
  runner method. Having the option is not proof that the full suite ran.
- The loop validates skill bodies after their YAML frontmatter was separated.
  The [structure validator](https://github.com/NousResearch/hermes-agent-self-evolution/blob/0a929e3aa20e15cf04dc7c28492a7d41a5139125/evolution/core/constraints.py)
  expects that frontmatter in its input. This is a static wiring inconsistency
  requiring a focused runtime reproduction before adoption.
- The wired [fitness metric](https://github.com/NousResearch/hermes-agent-self-evolution/blob/0a929e3aa20e15cf04dc7c28492a7d41a5139125/evolution/core/fitness.py)
  primarily scores word overlap. It does not establish that a real project,
  tool invocation or browser task succeeded. The main loop writes candidate
  files and metrics into an output directory.
- [Model defaults](https://github.com/NousResearch/hermes-agent-self-evolution/blob/0a929e3aa20e15cf04dc7c28492a7d41a5139125/evolution/core/config.py)
  use OpenAI model names. The external-history importer filters secret-like
  text, then sends candidate conversation excerpts to its configured scoring
  model. This is not Meu's provider/ownership policy and needs explicit adaptation.

These are source observations, not claims that the external project was
installed, benchmarked or exercised successfully here.

## Proposed Meu trial

Start with one existing skill and synthetic/curated project fixtures. Pin every
optimizer/evaluator call to the session's selected provider and bound the run's
request/token budget. Record baseline, candidate, actual tests, delivery results
and rollback data locally. Use the canonical test runner and Coordinator's
existing acceptance/review evidence rather than word overlap alone.

Apply passing skill versions on the next conversation boundary, preserving
prompt caching and the existing memory/skill approval defaults. Keep installed
application code changes in the normal development/test/release process.
The UI/connection work and pending physical-device acceptance remain ahead of
any production self-evolution integration.
