"""Explainable relevance ranking: weighted signals, every point carries a reason and a component.

A file's score is the sum of the signals that fire for it; ``WEIGHTS`` is the single table to
tune. Files explicitly named, or defining a symbol the query names, are *seeds*; graph signals
(dependency, reverse dependency, distance, tests) are measured from the seeds.

Phase 7 adds two optional DISCOVERY signals, semantic similarity and project memory. They are
capped well below structural evidence (``semantic_max`` < a direct dependency < an exact
symbol < an explicit file), never seed graph signals, never apply to protected or
security-sensitive paths, and a file found only through them is ``discovery_only``: it can be
read as context but is never chosen as an edit target.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from meu_coding.graph import RepositoryGraph, normalize_path
from meu_coding.interfaces import RankedItem, RepositoryAnalysis

WEIGHTS = {
    "explicit_file": 100.0,
    "exact_symbol": 45.0,
    "extra_symbol": 10.0,
    "weak_symbol": 8.0,
    "filename": 25.0,
    "path_component": 5.0,
    "path_component_cap": 15.0,
    "token_overlap": 15.0,
    "direct_dependency": 18.0,
    "reverse_dependency": 14.0,
    "distance_two": 6.0,
    "test_relationship": 12.0,
    "has_related_test": 3.0,
    "recently_changed": 8.0,
    "semantic_max": 17.0,  # always below a direct dependency (18)
    "memory_note": 5.0,
}
SEMANTIC_FLOOR = 0.25
SEMANTIC_GATE = 0.15  # absolute similarity above the floor needed for full strength


def semantic_strength(similarity: float, best: float) -> float:
    """0..1. Relative to the query's best hit (squared, so the runners-up fade quickly), and gated
    by absolute similarity so a weak best hit stays weak. Tuned on the MEU benchmark
    (scripts/meu_coding_semantic_benchmark.py); exact structural results kept their rank."""
    if similarity <= SEMANTIC_FLOOR or best <= SEMANTIC_FLOOR:
        return 0.0
    relative = (similarity - SEMANTIC_FLOOR) / (best - SEMANTIC_FLOOR)
    gate = min(1.0, (similarity - SEMANTIC_FLOOR) / SEMANTIC_GATE)
    return max(0.0, min(1.0, relative * relative * gate))

COMPONENT = {
    "explicit_file": "path_file_match", "exact_symbol": "symbol_match", "extra_symbol": "symbol_match",
    "weak_symbol": "symbol_match", "filename": "path_file_match", "path_component": "path_file_match",
    "token_overlap": "path_file_match", "direct_dependency": "dependency_proximity",
    "reverse_dependency": "dependency_proximity", "distance_two": "structural_graph",
    "test_relationship": "test_relation", "has_related_test": "test_relation", "recently_changed": "recent_change",
    "semantic": "semantic_embedding", "memory_note": "memory",
}

_STOPWORDS = frozenset("""
a an and are as at be but by can do does fix for from how i in into is it its me my not of
on or our please should so that the this to up use we what when where which why with you
add make change update file files code function class method module test tests bug error
""".split())
_IDENT = re.compile(r"`?([A-Za-z_][A-Za-z0-9_]*)(`|\()?")
_PATHLIKE = re.compile(r"[\w.\-]+(?:[/\\][\w.\-]+)+|[\w\-]+\.[A-Za-z][A-Za-z0-9]{0,4}\b")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def split_words(text: str) -> list[str]:
    return [w.lower() for part in re.split(r"[^A-Za-z0-9]+", text) for w in _CAMEL.findall(part)]


def is_test_path(path: str) -> bool:
    name = posixpath.basename(path)
    parts = path.split("/")[:-1]
    return (name.startswith("test_") or "_test." in name or ".test." in name or ".spec." in name
            or any(p in {"tests", "test", "__tests__", "spec"} for p in parts))


def tested_stem(path: str) -> str:
    return posixpath.basename(path).split(".")[0].removeprefix("test_").removesuffix("_test")


@dataclass(frozen=True)
class ParsedQuery:
    text: str
    paths: tuple[str, ...]
    strong_identifiers: frozenset[str]
    weak_identifiers: frozenset[str]
    tokens: tuple[str, ...]


def parse_query(query: str) -> ParsedQuery:
    paths = tuple(dict.fromkeys(normalize_path(m) for m in _PATHLIKE.findall(query)))
    strong, weak = set(), set()
    for match in _IDENT.finditer(query):
        name, marker = match.group(1), match.group(2)
        looks_like_code = (marker or match.group(0).startswith("`") or "_" in name
                           or any(c.isupper() for c in name[1:]) or any(c.isdigit() for c in name))
        (strong if looks_like_code else weak).add(name)
    tokens = tuple(dict.fromkeys(t for t in split_words(query) if len(t) > 1 and t not in _STOPWORDS))
    return ParsedQuery(query, paths, frozenset(strong), frozenset(weak - strong), tokens)


@dataclass
class _Score:
    points: float = 0.0
    reasons: list[tuple[float, str]] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    components: list[tuple[str, float]] = field(default_factory=list)

    def add(self, points: float, reason: str, signal: str) -> None:
        self.points += points
        self.reasons.append((points, reason))
        self.components.append((COMPONENT[signal], round(points, 2)))


class RelevanceEngine:
    """Scores only *candidate* files: those sharing a basename with a mentioned path, a
    (case-insensitive) definition name with a query identifier, or a word with the query.
    Every lexical signal needs one of those, so the result equals scoring every file; the
    inverted indexes behind it are maintained per file by ``update_path``/``remove_path``."""

    def __init__(self, analysis: RepositoryAnalysis, graph: RepositoryGraph) -> None:
        self.analysis = analysis
        self.graph = graph
        self._paths: set[str] = set()
        self._definitions: dict[str, tuple[str, ...]] = {}
        self._words: dict[str, frozenset[str]] = {}
        self._by_word: dict[str, set[str]] = {}
        self._by_lower_name: dict[str, set[str]] = {}
        self._by_basename: dict[str, set[str]] = {}
        self._tests_by_stem: dict[str, set[str]] = {}
        self._tests: set[str] = set()
        for path in sorted(analysis.files_by_path):
            self.update_path(path)

    def update_path(self, path: str) -> None:
        self.remove_path(path)
        self._paths.add(path)
        names = tuple(dict.fromkeys(s.name for s in self.graph.symbols_for_file(path)))
        self._definitions[path] = names
        words = set(split_words(path))
        for name in names:
            words.update(split_words(name))
            self._by_lower_name.setdefault(name.lower(), set()).add(path)
        self._words[path] = frozenset(words)
        for word in words:
            self._by_word.setdefault(word, set()).add(path)
        self._by_basename.setdefault(posixpath.basename(path), set()).add(path)
        if is_test_path(path):
            self._tests.add(path)
            self._tests_by_stem.setdefault(tested_stem(path), set()).add(path)

    def remove_path(self, path: str) -> None:
        if path not in self._paths:
            return
        self._paths.discard(path)
        if path in self._tests:
            self._tests.discard(path)
            _discard(self._tests_by_stem, tested_stem(path), path)
        for word in self._words.pop(path, ()):
            _discard(self._by_word, word, path)
        for name in self._definitions.pop(path, ()):
            _discard(self._by_lower_name, name.lower(), path)
        _discard(self._by_basename, posixpath.basename(path), path)

    def _candidates(self, parsed: ParsedQuery) -> list[str]:
        found: set[str] = set()
        for mention in parsed.paths:
            found |= self._by_basename.get(posixpath.basename(mention), set())
        for identifier in parsed.strong_identifiers | parsed.weak_identifiers:
            found |= self._by_lower_name.get(identifier.lower(), set())
        for token in parsed.tokens:
            found |= self._by_word.get(token, set())
        return sorted(found)

    def rank(self, query: str, limit: int | None = 50, recently_changed: Iterable[str] = (),
             semantic_hits: Iterable = (), memory_paths: Iterable[tuple[str, str]] = ()) -> tuple[RankedItem, ...]:
        parsed = parse_query(query)
        scores: dict[str, _Score] = {}
        for path in self._candidates(parsed):
            self._lexical(parsed, path, scores)
        seeds = sorted(p for p, s in scores.items() if s.symbols or self._explicit(parsed, p))
        self._graph_signals(seeds, scores)
        for path in sorted(set(recently_changed) & self._paths):
            if path in scores:
                scores[path].add(WEIGHTS["recently_changed"], "recently changed", "recently_changed")
        self._discovery_signals(semantic_hits, memory_paths, scores)
        ranked = [self._item(p, s) for p, s in scores.items() if s.points > 0]
        ranked.sort(key=lambda item: (-item.score, item.path))
        return tuple(ranked[:limit] if limit else ranked)

    def _discovery_signals(self, semantic_hits: Iterable, memory_paths: Iterable[tuple[str, str]],
                           scores: dict[str, _Score]) -> None:
        """Bounded, explained, and never for protected or security-sensitive files."""
        from meu_coding.scope import is_protected, is_security_path

        hits = [h for h in semantic_hits
                if h.path in self._paths and not is_protected(h.path) and not is_security_path(h.path)]
        best = max((h.similarity for h in hits), default=0.0)
        for hit in hits:
            strength = semantic_strength(hit.similarity, best)
            if strength > 0:
                self._score(scores, hit.path).add(round(WEIGHTS["semantic_max"] * strength, 2), hit.reason, "semantic")
        for path, note in memory_paths:
            if path in self._paths and not is_protected(path) and not is_security_path(path):
                self._score(scores, path).add(WEIGHTS["memory_note"], f"project memory: {note[:80]}", "memory_note")

    @staticmethod
    def _item(path: str, score: _Score) -> RankedItem:
        reasons = tuple(r for _, r in sorted(score.reasons, key=lambda pr: -pr[0]))
        return RankedItem(path, round(score.points, 1), reasons, tuple(score.symbols), tuple(score.components))

    @staticmethod
    def _explicit(parsed: ParsedQuery, path: str) -> bool:
        return any(path == m or path.endswith("/" + m) for m in parsed.paths)

    def _lexical(self, parsed: ParsedQuery, path: str, scores: dict[str, _Score]) -> None:
        score = _Score()
        if self._explicit(parsed, path):
            score.add(WEIGHTS["explicit_file"], "explicitly mentioned", "explicit_file")
        self._symbol_signals(parsed, path, score)
        self._name_signals(parsed, path, score)
        if score.points:
            scores[path] = score

    def _symbol_signals(self, parsed: ParsedQuery, path: str, score: _Score) -> None:
        defined = self._definitions[path]
        exact = [n for n in defined if n in parsed.strong_identifiers]
        for index, name in enumerate(exact):
            score.add(WEIGHTS["exact_symbol"] if index == 0 else WEIGHTS["extra_symbol"],
                      f"defines symbol {name}", "exact_symbol" if index == 0 else "extra_symbol")
            score.symbols.append(name)
        if exact:
            return
        lowered = {i.lower() for i in parsed.weak_identifiers | parsed.strong_identifiers}
        weak = [n for n in defined if n.lower() in lowered and len(n) > 3]
        if weak:
            score.add(WEIGHTS["weak_symbol"], f"defines {weak[0]} (case-insensitive mention)", "weak_symbol")

    def _name_signals(self, parsed: ParsedQuery, path: str, score: _Score) -> None:
        if not parsed.tokens:
            return
        stem_words = tuple(split_words(posixpath.splitext(posixpath.basename(path))[0]))
        if stem_words and _contains_run(parsed.tokens, stem_words):
            score.add(WEIGHTS["filename"], "filename matches query", "filename")
        directories = {w for d in path.split("/")[:-1] for w in split_words(d)}
        dir_hits = sorted(directories & set(parsed.tokens))
        if dir_hits:
            points = min(WEIGHTS["path_component"] * len(dir_hits), WEIGHTS["path_component_cap"])
            score.add(points, "path matches " + ", ".join(dir_hits), "path_component")
        overlap = [t for t in parsed.tokens if t in self._words[path]]
        if overlap:
            score.add(WEIGHTS["token_overlap"] * len(overlap) / len(parsed.tokens),
                      "keyword overlap: " + ", ".join(overlap), "token_overlap")

    def _graph_signals(self, seeds: list[str], scores: dict[str, _Score]) -> None:
        for seed in seeds:
            for dep in self.graph.get_dependencies(seed):
                self._score(scores, dep).add(WEIGHTS["direct_dependency"], f"imported by {seed}", "direct_dependency")
            for rdep in self.graph.get_reverse_dependencies(seed):
                self._score(scores, rdep).add(WEIGHTS["reverse_dependency"], f"imports {seed}", "reverse_dependency")
            for other, distance in self.graph.related_files(seed, 2).items():
                if distance == 2:
                    self._score(scores, other).add(WEIGHTS["distance_two"], f"two imports from {seed}", "distance_two")
            self._test_signals(seed, scores)

    def _test_signals(self, seed: str, scores: dict[str, _Score]) -> None:
        if is_test_path(seed):
            return
        stem = tested_stem(seed)
        importers = set(self.graph.get_reverse_dependencies(seed))
        related = sorted(self._tests_by_stem.get(stem, set()) | (importers & self._tests))
        for test in related:
            self._score(scores, test).add(WEIGHTS["test_relationship"], f"tests {seed}", "test_relationship")
        if related:
            self._score(scores, seed).add(WEIGHTS["has_related_test"], f"related test exists: {related[0]}",
                                          "has_related_test")

    @staticmethod
    def _score(scores: dict[str, _Score], path: str) -> _Score:
        return scores.setdefault(path, _Score())


def _contains_run(tokens: tuple[str, ...], words: tuple[str, ...]) -> bool:
    size = len(words)
    return any(tokens[i:i + size] == words for i in range(len(tokens) - size + 1))


def _discard(index: dict[str, set[str]], key: str, path: str) -> None:
    bucket = index.get(key)
    if bucket is not None:
        bucket.discard(path)
        if not bucket:
            del index[key]
