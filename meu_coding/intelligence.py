"""Public phase-1 API: one read-only, incrementally maintained view of a repository.

Two-stage indexing:

* **fast index** (``analyze_repository``): every file's path, language, imports and
  definitions, from line scanners; usable as soon as it finishes.
* **deep index** (on demand): the stdlib AST (or tree-sitter) with high-value references,
  only for files that matter: explicitly mentioned or highly ranked for a query, their
  direct dependencies and dependants, and recently changed files. ``deep_analyze()`` deepens
  any set of paths explicitly.

``refresh_changed_files`` touches only added, modified and removed files; the graph and the
relevance index are updated per file, never rebuilt. It is the ONE change path: the optional
semantic index (Phase 7) is updated from it too (changed chunks only), so there is no second
watcher and no second notion of "what changed".

Not wired into the Meu agent loop yet. Everything here reads; persisting the optional
extraction cache is the only write, and only to the location the caller gives the cache.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from meu_coding.cache import MemoryCache, content_digest
from meu_coding.context_builder import ContextBuilder, ContextLimits
from meu_coding.graph import RepositoryGraph, normalize_path
from meu_coding.interfaces import (
    DEEP,
    FAST,
    ContextBundle,
    ExtractionResult,
    RankedItem,
    RepositoryAnalysis,
    RepositoryFile,
    Symbol,
)
from meu_coding.relevance import RelevanceEngine
from meu_coding.repo_index import IndexConfig, RepositoryIndexer, language_for
from meu_coding.semantic_index import SemanticLayer
from meu_coding.semantic_search import layer_search
from meu_coding.symbols import SymbolExtractor

SEMANTIC_TOP_K = 12

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeSet:
    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def changed(self) -> tuple[str, ...]:
        return tuple(sorted(self.added + self.modified))


@dataclass
class ScanStats:
    files: int = 0
    extracted_fast: int = 0
    extracted_deep: int = 0
    cache_hits: int = 0
    errors: int = 0

    @property
    def extracted(self) -> int:
        return self.extracted_fast + self.extracted_deep


class RepositoryIntelligence:
    def __init__(self, root: str | Path, config: IndexConfig | None = None,
                 extractor: SymbolExtractor | None = None, cache: MemoryCache | None = None,
                 limits: ContextLimits | None = None, deep_budget: int = 20,
                 semantic: SemanticLayer | None = None) -> None:
        self.indexer = RepositoryIndexer(root, config)
        self.root = self.indexer.root
        self.extractor = extractor or SymbolExtractor()
        self.cache = cache if cache is not None else MemoryCache()
        self.limits = limits
        self.deep_budget = deep_budget
        self.stats = ScanStats()
        self.recently_changed: frozenset[str] = frozenset()
        self._analysis: RepositoryAnalysis | None = None
        self._graph: RepositoryGraph | None = None
        self._engine: RelevanceEngine | None = None
        self.semantic = semantic
        self.last_ranking: dict = {}

    # ── fast index ──────────────────────────────────────────────────────────

    def analyze_repository(self) -> RepositoryAnalysis:
        """(Re)build the fast index; unchanged files come from the cache."""
        self.stats = ScanStats()
        files = self.indexer.scan(known=self._known_files())
        self.stats.files = len(files)
        previous = self._analysis.extractions if self._analysis is not None else {}
        extractions = {}
        for file in files:
            keep = previous.get(file.path)
            depth = DEEP if keep is not None and keep.depth == DEEP else FAST
            extractions[file.path] = self._extract(file, depth)
        self._cache_call("prune", set(extractions))
        self._cache_call("save")
        self._analysis = RepositoryAnalysis.build(str(self.root), files, extractions)
        self._graph = RepositoryGraph(files, extractions)
        self._engine = RelevanceEngine(self._analysis, self._graph)
        if self.semantic is not None:
            self.semantic.sync(self.root, files, extractions)
        return self._analysis

    def _known_files(self) -> dict[str, RepositoryFile]:
        if self._analysis is not None:
            return dict(self._analysis.files_by_path)
        known = self._cache_call("known_files") or {}
        return {
            path: RepositoryFile(path, language_for(path), Path(path).suffix.lower(), size, mtime_ns)
            for path, (size, mtime_ns) in known.items()
        }

    # ── incremental refresh ─────────────────────────────────────────────────

    def refresh_changed_files(self, paths: Iterable[str] | None = None) -> ChangeSet:
        """Apply what changed on disk. With ``paths`` (e.g. the files a write just touched)
        only those are checked; without, the tree is rescanned by metadata, which reads no
        unchanged file. Changed files are deep-parsed and boosted in ranking."""
        analysis = self.analysis
        self.stats = ScanStats()
        previous = analysis.files_by_path
        if paths is None:
            current = {f.path: f for f in self.indexer.scan(known=previous)}
            candidates = set(previous) | set(current)
        else:
            candidates = {normalize_path(p) for p in paths}
            current = {}
            for path in candidates:
                record = self.indexer.file_record(path, known=previous)
                if record is not None:
                    current[path] = record
        changes = _diff(previous, current, candidates)
        for path in changes.removed:
            self._remove(path)
        for path in changes.changed:
            self._apply(current[path], self._extract(current[path], DEEP))
        if self.semantic is not None:
            for path in changes.removed:
                self.semantic.remove_file(path)
            self.semantic.update_files(self.root, [current[p] for p in changes.changed], analysis.extractions)
        self.recently_changed = (self.recently_changed - set(changes.removed)) | set(changes.changed)
        self.stats.files = len(analysis.files_by_path)
        self._cache_call("prune", set(analysis.files_by_path))
        self._cache_call("save")
        return changes

    def _apply(self, file: RepositoryFile, extraction: ExtractionResult) -> None:
        self._analysis.put(file, extraction)
        self._graph.update_file(file, extraction)
        self._engine.update_path(file.path)

    def _remove(self, path: str) -> None:
        self._engine.remove_path(path)
        self._graph.remove_file(path)
        self._analysis.remove(path)

    # ── deep index ──────────────────────────────────────────────────────────

    def deep_analyze(self, paths: Iterable[str] | None = None) -> tuple[str, ...]:
        """Deep-parse ``paths`` (every indexed file when ``None``); returns those deepened."""
        analysis = self.analysis
        targets = analysis.files_by_path if paths is None else [normalize_path(p) for p in paths]
        deepened = []
        for path in sorted(set(targets)):
            file = analysis.file(path)
            current = analysis.extractions.get(path)
            if file is None or current is None or current.depth == DEEP:
                continue
            self._apply(file, self._extract(file, DEEP))
            deepened.append(path)
        return tuple(deepened)

    def _deep_targets(self, ranked: tuple[RankedItem, ...]) -> list[str]:
        top = [item.path for item in ranked[: self.deep_budget]]
        near: list[str] = []
        for path in top[:3]:
            near += self.graph.get_dependencies(path) + self.graph.get_reverse_dependencies(path)
        recent = [item.path for item in ranked if item.path in self.recently_changed]
        return list(dict.fromkeys(top + near[: self.deep_budget] + recent))

    # ── extraction ──────────────────────────────────────────────────────────

    def _extract(self, file: RepositoryFile, depth: str) -> ExtractionResult:
        if not self.extractor.supports(file.language):
            result = ExtractionResult(file.path, (), "none")
            self._cache_call("put", file, result, None)
            return result
        data: bytes | None = None
        digest = None
        if self.cache.verify_content:
            data = self._read(file)
            digest = content_digest(data) if data is not None else None
        cached = self._cache_call("get", file, digest)
        if cached is not None and (depth == FAST or cached.depth == DEEP):
            self.stats.cache_hits += 1
            return cached
        data = data if data is not None else self._read(file)
        if data is None:
            return ExtractionResult(file.path, (), "none", "unreadable")
        result = self.extractor.extract(file.path, data.decode("utf-8", errors="replace"), file.language, depth)
        if depth == DEEP:
            self.stats.extracted_deep += 1
        else:
            self.stats.extracted_fast += 1
        self.stats.errors += result.error is not None
        self._cache_call("put", file, result, digest)
        return result

    def _read(self, file: RepositoryFile) -> bytes | None:
        try:
            return (self.root / file.path).read_bytes()
        except OSError:
            return None

    def _cache_call(self, method: str, *args):
        try:
            return getattr(self.cache, method)(*args)
        except Exception as exc:  # a third-party cache must never break analysis
            logger.warning("meu_coding cache %s failed: %s", method, exc, exc_info=True)
            return None

    def save_cache(self) -> None:
        """Persist deep results gathered by queries (refresh and analysis save on their own)."""
        self._cache_call("save")

    # ── state ───────────────────────────────────────────────────────────────

    def _require(self) -> None:
        if self._analysis is None:
            self.analyze_repository()

    @property
    def analysis(self) -> RepositoryAnalysis:
        self._require()
        return self._analysis

    @property
    def graph(self) -> RepositoryGraph:
        self._require()
        return self._graph

    def symbol_counts(self) -> dict[str, int]:
        counts = {"definitions": 0, "imports": 0, "references": 0, "deep_files": 0}
        for extraction in self.analysis.extractions.values():
            counts["definitions"] += len(extraction.definitions)
            counts["imports"] += len(extraction.imports)
            counts["references"] += len(extraction.references)
            counts["deep_files"] += extraction.depth == DEEP
        return counts

    # ── queries ─────────────────────────────────────────────────────────────

    def rank(self, query: str, limit: int | None = 50,
             memory_paths: tuple[tuple[str, str], ...] = ()) -> tuple[RankedItem, ...]:
        self._require()
        hits = layer_search(self.semantic, query, SEMANTIC_TOP_K)
        ranked = self._engine.rank(query, limit, self.recently_changed, hits, memory_paths)
        self.last_ranking = ranking_sources(ranked, hits, self.semantic)
        return ranked

    def find_relevant_context(self, query: str, budget: int = 12_000) -> ContextBundle:
        return self.context_with_ranking(query, budget)[0]

    def context_with_ranking(self, query: str, budget: int = 12_000,
                             memory_paths: tuple[tuple[str, str], ...] = ()) -> tuple[ContextBundle, tuple[RankedItem, ...]]:
        """The context bundle plus the ranking it was built from, so callers that need both
        do not rank twice."""
        ranked = self.rank(query, memory_paths=memory_paths)
        if self.deep_analyze(self._deep_targets(ranked)):
            ranked = self.rank(query, memory_paths=memory_paths)
        return ContextBuilder(self.analysis, self.graph, self.limits).build(query, ranked, budget), ranked

    def lookup_symbol(self, name: str) -> tuple[Symbol, ...]:
        return self.graph.lookup_symbol(name)

    def get_dependencies(self, target: str, include_external: bool = False) -> tuple[str, ...]:
        return self.graph.get_dependencies(target, include_external)

    def get_reverse_dependencies(self, target: str) -> tuple[str, ...]:
        return self.graph.get_reverse_dependencies(target)


def ranking_sources(ranked: tuple[RankedItem, ...], hits, semantic: SemanticLayer | None) -> dict:
    """Observability: which evidence produced the ranking (counts only, no file contents)."""
    counts: dict[str, int] = {}
    for item in ranked:
        for component in item.component_totals():
            counts[component] = counts.get(component, 0) + 1
    return {"items": len(ranked), "components": counts, "semantic_hits": len(hits),
            "discovery_only": sum(1 for item in ranked if item.discovery_only),
            "semantic_status": semantic.status if semantic is not None else "off",
            "semantic_query_ms": semantic.last_query_ms if semantic is not None else 0.0}


def _diff(previous: dict[str, RepositoryFile], current: dict[str, RepositoryFile],
          candidates: set[str]) -> ChangeSet:
    added, modified, removed = [], [], []
    for path in sorted(candidates):
        old, new = previous.get(path), current.get(path)
        if old is None and new is not None:
            added.append(path)
        elif old is not None and new is None:
            removed.append(path)
        elif old is not None and (old.size, old.mtime_ns) != (new.size, new.mtime_ns):
            modified.append(path)
    return ChangeSet(tuple(added), tuple(modified), tuple(removed))


def analyze_repository(root: str | Path, **options) -> RepositoryIntelligence:
    intelligence = RepositoryIntelligence(root, **options)
    intelligence.analyze_repository()
    return intelligence
