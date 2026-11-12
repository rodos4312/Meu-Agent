"""``semantic_search(query, top_k)`` over a :class:`SemanticIndex`.

Returns discovery hits (file, chunk, similarity, lines, reason). It never returns context:
hits feed :class:`meu_coding.relevance.RelevanceEngine`, where structural evidence outranks
them, and they never authorize an edit (see ``RankedItem.discovery_only``).

Search is exact when NumPy is already installed (one matrix product over all chunks). Without
it, a pure-Python two-stage search scores one centroid per file, then every chunk of the best
``FILE_SHORTLIST`` files; this keeps queries well under a second on large repositories.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass

from meu_coding.embeddings import EmbeddingUnavailable, cosine, normalize
from meu_coding.semantic_index import SemanticIndex, SemanticLayer

MIN_SIMILARITY = 0.25
FILE_SHORTLIST = 60


@dataclass(frozen=True)
class SemanticHit:
    path: str
    chunk_id: str
    symbol: str
    container: str
    kind: str
    start_line: int
    end_line: int
    similarity: float

    @property
    def reason(self) -> str:
        where = f"{self.container}.{self.symbol}" if self.container and self.symbol else self.symbol or self.kind
        return f"semantic similarity {self.similarity:.2f} ({where}, lines {self.start_line}-{self.end_line})"

    def to_dict(self) -> dict:
        return {"path": self.path, "chunk": self.symbol or self.kind, "container": self.container,
                "similarity": round(self.similarity, 3), "lines": [self.start_line, self.end_line],
                "reason": self.reason}


class _Prepared:
    """Per-index search structures, rebuilt only when the index changed."""

    def __init__(self, cache) -> None:
        self.paths, self.chunk_ids, self.vectors, self.by_file = cache
        self.source = cache
        try:
            import numpy as np  # optional acceleration; never installed by the Coding Engine
        except ImportError:
            np = None
        self.np = np
        self.matrix = np.asarray(self.vectors, dtype="float32") if np is not None and self.vectors else None
        self.files = sorted(self.by_file)
        self.centroids = [] if self.matrix is not None else [
            normalize([sum(column) for column in zip(*(self.vectors[i] for i in self.by_file[path]), strict=True)])
            for path in self.files]

    def scores(self, query) -> list[tuple[float, int]]:
        if self.matrix is not None:
            values = self.matrix @ self.np.asarray(query, dtype="float32")
            return [(float(values[i]), i) for i in range(len(values))]
        shortlist = heapq.nlargest(FILE_SHORTLIST, range(len(self.files)),
                                   key=lambda f: cosine(query, self.centroids[f]))
        return [(cosine(query, self.vectors[i]), i) for f in shortlist for i in self.by_file[self.files[f]]]


_PREPARED: dict[int, _Prepared] = {}


def _prepared(index: SemanticIndex) -> _Prepared:
    cache = index.search_cache()
    current = _PREPARED.get(id(index))
    if current is None or current.source is not cache:
        current = _Prepared(cache)
        _PREPARED[id(index)] = current
    return current


def semantic_search(index: SemanticIndex, query: str, top_k: int = 10,
                    min_similarity: float = MIN_SIMILARITY) -> list[SemanticHit]:
    """Best chunk per file first, deterministic order (similarity, then path, then chunk)."""
    if not query.strip():
        return []
    prepared = _prepared(index)
    if not prepared.vectors:
        return []
    query_vector = index.provider.embed([query])[0]
    best: dict[str, tuple[float, str]] = {}
    for score, i in prepared.scores(query_vector):
        if score < min_similarity:
            continue
        path, chunk_id = prepared.paths[i], prepared.chunk_ids[i]
        if path not in best or (score, chunk_id) > best[path]:
            best[path] = (score, chunk_id)
    top = heapq.nsmallest(top_k, best.items(), key=lambda kv: (-kv[1][0], kv[0]))
    hits = []
    for path, (score, chunk_id) in top:
        meta = index.chunk(chunk_id) or {}
        hits.append(SemanticHit(path, chunk_id, meta.get("symbol") or "", meta.get("container") or "",
                                meta.get("kind") or "", meta.get("start_line") or 0, meta.get("end_line") or 0,
                                round(score, 4)))
    return hits


def layer_search(layer: SemanticLayer | None, query: str, top_k: int = 10) -> list[SemanticHit]:
    """Never raises and never fakes: an unavailable layer returns no hits."""
    if layer is None or not layer.available:
        return []
    started = time.perf_counter()
    try:
        hits = semantic_search(layer.index, query, top_k)
    except EmbeddingUnavailable as exc:
        layer.status, layer.reason = "unavailable", str(exc)
        return []
    layer.last_query_ms = round((time.perf_counter() - started) * 1000, 2)
    return hits
