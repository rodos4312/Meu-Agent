"""Meu coding engine, phase 1: read-only repository intelligence.

Indexes a repository, extracts symbols, builds a dependency graph, ranks files for a query
with explainable signals and packs a budgeted LLM context. Nothing here writes source
files, runs shell commands, executes repository code or mutates git; file writes, patches,
approvals, terminals and worktrees stay with the existing Meu systems.
"""

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

__all__ = [
    "ChangeSet",
    "ContextBundle",
    "ContextItem",
    "DependencyEdge",
    "EdgeKind",
    "RankedItem",
    "RepositoryAnalysis",
    "RepositoryFile",
    "RepositoryIntelligence",
    "Symbol",
    "analyze_repository",
]
