"""Turns ranked files into a budgeted LLM context without dumping whole files.

Per ranked file, in rank order:

* a file that defines a symbol the query names contributes that symbol's definition with
  a few lines of leading context (decorators, comments), capped at ``max_symbol_lines``;
* any other file contributes an outline: its imports and the signature line of each
  class/function/method, capped at ``max_outline_lines``.

Each item opens with a short header (path, why it was chosen, nearest dependencies). The
budget is in characters, since no model-neutral tokenizer exists yet; an item that does
not fit is trimmed line by line, and dropped (listed in ``omitted``) if even a minimal
version does not fit.
"""

from __future__ import annotations

from dataclasses import dataclass

from meu_coding.graph import RepositoryGraph
from meu_coding.interfaces import ContextBundle, ContextItem, RankedItem, RepositoryAnalysis
from meu_coding.repo_index import read_source

_SIGNATURE_KINDS = frozenset({"class", "function", "method"})
_MIN_BODY_LINES = 3


@dataclass(frozen=True)
class ContextLimits:
    max_symbol_lines: int = 60
    leading_lines: int = 3
    max_outline_lines: int = 30
    max_items: int = 12
    max_header_links: int = 3


class ContextBuilder:
    def __init__(self, analysis: RepositoryAnalysis, graph: RepositoryGraph,
                 limits: ContextLimits | None = None) -> None:
        self.analysis = analysis
        self.graph = graph
        self.limits = limits or ContextLimits()

    def build(self, query: str, ranked: tuple[RankedItem, ...], budget: int) -> ContextBundle:
        items: list[ContextItem] = []
        omitted: list[str] = []
        remaining = budget
        for entry in ranked:
            if len(items) >= self.limits.max_items:
                omitted.append(entry.path)
                continue
            item = self._fit(self._item(entry), remaining)
            if item is None:
                omitted.append(entry.path)
                continue
            items.append(item)
            remaining -= item.size + 2  # the blank line ``render`` puts between items
        return ContextBundle(query, budget, tuple(items), tuple(omitted))

    # ── one file ────────────────────────────────────────────────────────────

    def _item(self, entry: RankedItem) -> tuple[ContextItem, str, list[str]]:
        try:
            lines = read_source(self.analysis.root, entry.path).splitlines()
        except OSError:
            lines = []
        spans = self._symbol_spans(entry, len(lines))
        if spans:
            body = [_numbered(lines, n) for start, end in spans for n in range(start, end + 1)]
            start, end = spans[0][0], spans[-1][1]
        else:
            numbers = self._outline_lines(entry.path, len(lines))
            body = [_numbered(lines, n) for n in numbers]
            start, end = (numbers[0], numbers[-1]) if numbers else (0, 0)
        header = self._header(entry)
        item = ContextItem(entry.path, entry.symbols, "\n".join([header, *body]), entry.reasons, start, end)
        return item, header, body

    def _symbol_spans(self, entry: RankedItem, line_count: int) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        for symbol in self.graph.symbols_for_file(entry.path):
            if symbol.name not in entry.symbols:
                continue
            start = max(1, symbol.line - self.limits.leading_lines)
            natural_end = symbol.end_line or symbol.line + self.limits.max_symbol_lines
            end = min(natural_end, symbol.line + self.limits.max_symbol_lines - 1, line_count)
            spans.append((start, end))
        return _merge(spans)

    def _outline_lines(self, path: str, line_count: int) -> list[int]:
        extraction = self.analysis.extractions.get(path)
        if extraction is None:
            return list(range(1, min(line_count, self.limits.max_outline_lines) + 1))
        wanted = {s.line for s in extraction.imports}
        wanted |= {s.line for s in extraction.definitions if s.kind in _SIGNATURE_KINDS}
        return sorted(n for n in wanted if 1 <= n <= line_count)[: self.limits.max_outline_lines]

    def _header(self, entry: RankedItem) -> str:
        cap = self.limits.max_header_links
        lines = [f"# {entry.path} (score {entry.score:g}): {'; '.join(entry.reasons[:4])}"]
        deps = self.graph.get_dependencies(entry.path)[:cap]
        rdeps = self.graph.get_reverse_dependencies(entry.path)[:cap]
        if deps or rdeps:
            lines.append(f"# imports: {', '.join(deps) or '-'} | imported by: {', '.join(rdeps) or '-'}")
        return "\n".join(lines)

    # ── budget ──────────────────────────────────────────────────────────────

    @staticmethod
    def _fit(built: tuple[ContextItem, str, list[str]], remaining: int) -> ContextItem | None:
        item, header, body = built
        if item.size <= remaining:
            return item
        kept = list(body)
        while len(kept) > _MIN_BODY_LINES:
            kept.pop()
            excerpt = "\n".join([header, *kept, "# … trimmed to fit the context budget"])
            if len(excerpt) <= remaining:
                end = int(kept[-1].split("|", 1)[0])
                return ContextItem(item.path, item.symbols, excerpt, item.reasons, item.start_line, end)
        return None


def _numbered(lines: list[str], number: int) -> str:
    return f"{number:>5} | {lines[number - 1].rstrip()}"


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
