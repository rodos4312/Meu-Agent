"""Model-independent data shapes shared by every phase-1 component.

Paths are always repository-relative POSIX strings so results are identical on Windows
and POSIX hosts and stable across machines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    path: str
    language: str
    extension: str
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class Symbol:
    """A definition, import or reference found in a file.

    ``kind`` is one of ``class``, ``function``, ``method``, ``variable``, ``import`` or
    ``reference``. For an import, ``name`` is the imported module (relative imports keep
    their leading dots) and ``container`` holds the imported name, if any. For a
    reference, ``container`` is the enclosing definition's qualified name.
    """

    name: str
    kind: str
    path: str
    line: int
    language: str
    column: int | None = None
    container: str | None = None
    end_line: int | None = None

    @property
    def qualified_name(self) -> str:
        if self.kind in DEFINITION_KINDS and self.container:
            return f"{self.container}.{self.name}"
        return self.name

    @property
    def is_definition(self) -> bool:
        return self.kind in DEFINITION_KINDS


DEFINITION_KINDS = frozenset({"class", "function", "method", "variable"})

FAST = "fast"
"""Extraction depth: definitions and imports only, from a line scanner."""
DEEP = "deep"
"""Extraction depth: the best backend available, including high-value references."""


@dataclass(frozen=True)
class ExtractionResult:
    path: str
    symbols: tuple[Symbol, ...]
    backend: str
    error: str | None = None
    depth: str = DEEP

    @cached_property
    def definitions(self) -> tuple[Symbol, ...]:
        return tuple(s for s in self.symbols if s.is_definition)

    @cached_property
    def imports(self) -> tuple[Symbol, ...]:
        return tuple(s for s in self.symbols if s.kind == "import")

    @cached_property
    def references(self) -> tuple[Symbol, ...]:
        return tuple(s for s in self.symbols if s.kind == "reference")


class EdgeKind(str, Enum):
    IMPORTS = "imports"
    DEFINES = "defines"
    REFERENCES = "references"
    BELONGS_TO = "belongs_to"


@dataclass(frozen=True)
class DependencyEdge:
    """``source``/``target`` are node ids: a file path, ``module:<name>`` or
    ``symbol:<path>:<qualified name>:<line>``."""

    source: str
    target: str
    kind: EdgeKind


DISCOVERY_COMPONENTS = frozenset({"semantic_embedding", "memory"})


@dataclass(frozen=True)
class RankedItem:
    path: str
    score: float
    reasons: tuple[str, ...]
    symbols: tuple[str, ...] = ()
    # (component, points) per signal: structural_graph, symbol_match, path_file_match,
    # dependency_proximity, test_relation, recent_change, semantic_embedding, memory
    components: tuple[tuple[str, float], ...] = ()

    @property
    def discovery_only(self) -> bool:
        """Found only by semantic similarity or memory: may inform, never selects an edit target."""
        return bool(self.components) and all(name in DISCOVERY_COMPONENTS for name, _ in self.components)

    def component_totals(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for name, points in self.components:
            totals[name] = round(totals.get(name, 0.0) + points, 2)
        return totals


@dataclass(frozen=True)
class ContextItem:
    path: str
    symbols: tuple[str, ...]
    excerpt: str
    reasons: tuple[str, ...]
    start_line: int
    end_line: int

    @property
    def size(self) -> int:
        return len(self.excerpt)


@dataclass(frozen=True)
class ContextBundle:
    query: str
    budget: int
    items: tuple[ContextItem, ...]
    omitted: tuple[str, ...] = ()

    @property
    def size(self) -> int:
        return sum(item.size for item in self.items)

    def render(self) -> str:
        return "\n\n".join(item.excerpt for item in self.items)


@dataclass
class RepositoryAnalysis:
    """Per-file index state; updated in place one file at a time."""

    root: str
    files_by_path: dict[str, RepositoryFile] = field(default_factory=dict)
    extractions: dict[str, ExtractionResult] = field(default_factory=dict)
    _sorted: tuple[RepositoryFile, ...] | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def build(cls, root: str, files, extractions: dict[str, ExtractionResult]) -> RepositoryAnalysis:
        return cls(root, {f.path: f for f in files}, dict(extractions))

    @property
    def files(self) -> tuple[RepositoryFile, ...]:
        if self._sorted is None:
            self._sorted = tuple(self.files_by_path[p] for p in sorted(self.files_by_path))
        return self._sorted

    def file(self, path: str) -> RepositoryFile | None:
        return self.files_by_path.get(path)

    def put(self, file: RepositoryFile, extraction: ExtractionResult) -> None:
        self.files_by_path[file.path] = file
        self.extractions[file.path] = extraction
        self._sorted = None

    def remove(self, path: str) -> None:
        self.files_by_path.pop(path, None)
        self.extractions.pop(path, None)
        self._sorted = None

    @property
    def symbols(self) -> tuple[Symbol, ...]:
        return tuple(s for path in sorted(self.extractions) for s in self.extractions[path].symbols)


class SymbolExtractorBackend(Protocol):
    name: str

    def supports(self, language: str) -> bool: ...

    def extract(self, path: str, source: str, language: str) -> ExtractionResult: ...
