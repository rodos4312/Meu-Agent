"""Meu coding engine.

Repository intelligence (index, symbols, dependency graph, explainable ranking, budgeted
context) feeds Architect -> Coder -> Reviewer, which ends at an explicit approval boundary
(``CodingOrchestrator``, ``meu_coding.safe_execution``). See ``docs/MEU_CODING_ENGINE.md``.

Nothing here writes source files, runs shell commands, executes repository code or
mutates git; file writes, patches, approvals, terminals and worktrees stay with the
existing Meu systems.
"""

# Public names load on first use (PEP 562): importing a light sibling such as
# ``meu_coding.service_registry`` must not pay for the whole engine.
_EXPORTS = {
    "CodingTask": "coding_interfaces",
    "TaskConstraints": "coding_interfaces",
    "ChangeSet": "intelligence",
    "RepositoryIntelligence": "intelligence",
    "analyze_repository": "intelligence",
    "ContextBundle": "interfaces",
    "ContextItem": "interfaces",
    "DependencyEdge": "interfaces",
    "EdgeKind": "interfaces",
    "RankedItem": "interfaces",
    "RepositoryAnalysis": "interfaces",
    "RepositoryFile": "interfaces",
    "Symbol": "interfaces",
    "CodingOrchestrator": "orchestrator",
    "CodingResult": "orchestrator",
    "OutcomeStatus": "orchestrator",
}


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'meu_coding' has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(f"meu_coding.{module}"), name)
    globals()[name] = value
    return value


__all__ = [
    "ChangeSet",
    "CodingOrchestrator",
    "CodingResult",
    "CodingTask",
    "ContextBundle",
    "ContextItem",
    "DependencyEdge",
    "EdgeKind",
    "OutcomeStatus",
    "RankedItem",
    "RepositoryAnalysis",
    "RepositoryFile",
    "RepositoryIntelligence",
    "Symbol",
    "TaskConstraints",
    "analyze_repository",
]
