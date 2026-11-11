"""Impact analysis over the Phase 1 dependency graph.

Given files (and optionally symbols) that a plan or proposal changes, report what else is
likely affected and an explainable risk level. Read-only and graph-only: it never reads
file contents, so it costs dictionary lookups on the cached graph, not a scan.
"""

from __future__ import annotations

from collections.abc import Iterable

from meu_coding.coding_interfaces import ImpactReport, RiskLevel, RiskReason, max_risk
from meu_coding.graph import RepositoryGraph
from meu_coding.relevance import is_test_path, tested_stem
from meu_coding.scope import is_caller_path, is_config_path, is_security_path

MANY_REVERSE_MEDIUM = 8
MANY_REVERSE_HIGH = 25
HEAVY_REFERENCES = 5


class ImpactAnalyzer:
    def __init__(self, graph: RepositoryGraph) -> None:
        self.graph = graph
        self._tests_by_stem: dict[str, list[str]] | None = None

    def _tests_for(self, path: str) -> list[str]:
        if self._tests_by_stem is None:
            index: dict[str, list[str]] = {}
            for candidate in sorted(self.graph.files):
                if is_test_path(candidate):
                    index.setdefault(tested_stem(candidate), []).append(candidate)
            self._tests_by_stem = index
        return self._tests_by_stem.get(tested_stem(path), [])

    def analyze(self, changed_files: Iterable[str], changed_symbols: Iterable[str] = ()) -> ImpactReport:
        files = tuple(dict.fromkeys(changed_files))
        symbols = tuple(dict.fromkeys(changed_symbols))
        changed = set(files)
        direct = _ordered(d for f in files for d in self.graph.get_dependencies(f) if d not in changed)
        reverse = _ordered(r for f in files for r in self.graph.get_reverse_dependencies(f) if r not in changed)
        tests = self._affected_tests(files, reverse)
        config = _ordered(p for p in (*files, *direct) if is_config_path(p))
        callers = _ordered(p for p in reverse if is_caller_path(p) and not is_test_path(p))
        reasons = self._reasons(files, symbols, reverse, tests)
        return ImpactReport(
            changed_files=files, changed_symbols=symbols, direct_dependencies=direct,
            reverse_dependencies=reverse, affected_tests=tests, affected_config=config,
            callers=callers, risk=max_risk([r.level for r in reasons]), reasons=tuple(reasons),
        )

    def _affected_tests(self, files: tuple[str, ...], reverse: tuple[str, ...]) -> tuple[str, ...]:
        found = [f for f in files if is_test_path(f)]
        found += [r for r in reverse if is_test_path(r)]
        for path in files:
            if not is_test_path(path):
                found += self._tests_for(path)
                found += [p for p in self.graph.related_files(path) if is_test_path(p)]
        return _ordered(found)

    def _reasons(self, files, symbols, reverse, tests) -> list[RiskReason]:
        reasons = []
        for path in files:
            if is_security_path(path):
                reasons.append(RiskReason(RiskLevel.HIGH, f"security-sensitive code touched: {path}"))
            if is_config_path(path):
                reasons.append(RiskReason(RiskLevel.MEDIUM, f"configuration file touched: {path}"))
            if path not in self.graph.files:
                reasons.append(RiskReason(RiskLevel.LOW, f"new file: {path}"))
        reasons += self._symbol_reasons(files, symbols)
        if len(reverse) >= MANY_REVERSE_HIGH:
            reasons.append(RiskReason(RiskLevel.HIGH, f"{len(reverse)} files depend on the changed files"))
        elif len(reverse) >= MANY_REVERSE_MEDIUM:
            reasons.append(RiskReason(RiskLevel.MEDIUM, f"{len(reverse)} files depend on the changed files"))
        code_files = [f for f in files if not is_test_path(f) and not is_config_path(f)]
        if code_files and not tests:
            reasons.append(RiskReason(RiskLevel.MEDIUM, "no tests found for the changed files"))
        return reasons

    def _symbol_reasons(self, files: tuple[str, ...], symbols: tuple[str, ...]) -> list[RiskReason]:
        reasons = []
        changed = set(files)
        for name in symbols:
            short = name.rsplit(".", 1)[-1]
            outside = [p for p in self.graph.referencing_files(short) if p not in changed]
            defined_here = any(p in changed for p in self.graph.files_for_symbol(short))
            if defined_here and not short.startswith("_") and outside:
                reasons.append(RiskReason(RiskLevel.MEDIUM,
                                          f"public API changed: {name} is used by {len(outside)} other file(s)"))
            if len(outside) >= HEAVY_REFERENCES:
                reasons.append(RiskReason(RiskLevel.HIGH,
                                          f"heavily referenced symbol changed: {name} ({len(outside)} files)"))
        return reasons


def _ordered(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(items)))
