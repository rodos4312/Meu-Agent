# Meu Coordinator preview

Available in `0.1.0-dev.4` through **Settings → Model → Subagents → Meu Coordinator**.
The choice is profile-scoped and persisted through the existing delegation API.
It applies to new sessions; a running session retains its original tools and prompt.
Existing routes are not silently overwritten. The updated Python backend must contain
the bundled `plugins/delegation/meu_coordinator` plugin; replacing the desktop executable
alone does not update an older backend installation.

The parent LLM plans each subtask semantically using `workload`, `acceptance`,
`parallel_safe` and `write_paths`. Routine tasks and image interpretation use
DeepSeek Flash; complex implementation, debugging or review use DeepSeek Pro.
This provider uses the profile's native DeepSeek credentials. It makes no separate
planner request and does not use prompt-length/keyword rules to classify tasks.
Each helper's selected model remains fixed, including while the parent uses Auto.
The route/model label is included in the existing delegation results and progress.

Before any helper is built, the plan validator rejects missing acceptance checks,
invalid paths, conflicting declared write scopes, and tasks marked dependent that
were submitted as a parallel batch. Comparisons cover Windows case and separators.
The parent must submit dependent stages after their prerequisite results arrive.
Acceptance criteria and write scopes are inserted into each new child's initial
context, with instructions to report actual checks, artifacts and unresolved issues.

The parent is instructed to inspect results, integrate them, and use a complex
retry/reviewer when evidence warrants it. This is LLM-led coordination: it does not
guarantee correct complexity judgments, execute an autonomous persisted task DAG,
or enforce a filesystem sandbox. In particular, the validator checks declared
write scopes; it cannot prove a helper obeys them. No arbitrary scoring threshold
automatically declares a task verified. Ordinary stop/steer semantics, the two-child
process gate, flat delegation, privacy opt-outs and approval policies are unchanged.

Tests exercise bundled discovery and registry dispatch, safe/invalid parallel plans,
profile separation, stable schema bytes and actual child model requests through an
HTTP mock transport (only DeepSeek destinations, no Nous request). Windows desktop
E2E checks the real settings selection, persisted YAML and a full app restart under
an isolated `MEU_HOME` and Electron user-data directory.
