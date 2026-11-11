"""Meu coding engine.

Phase 1, read-only repository intelligence: indexes a repository, extracts symbols,
builds a dependency graph, ranks files for a query with explainable signals and packs a
budgeted LLM context.

Phase 2, orchestration: Architect -> Coder -> Reviewer over that context, ending at an
explicit approval boundary (``CodingOrchestrator``, ``meu_coding.execution``).

Nothing here writes source files, runs shell commands, executes repository code or
mutates git; file writes, patches, approvals, terminals and worktrees stay with the
existing Meu systems.
"""

from meu_coding.coding_interfaces import CodingTask, TaskConstraints
from meu_coding.intelligence import ChangeSet, RepositoryIntelligence, analyze_repository
from meu_coding.interfaces import (
    ContextBundle,
    ContextItem,
    DependencyEdge,
    EdgeKind,
    RankedItem,
    RepositoryAnalysis,
    RepositoryFile,
    Symbol,
)
from meu_coding.orchestrator import CodingOrchestrator, CodingResult, OutcomeStatus

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
