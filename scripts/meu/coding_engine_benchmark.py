"""Non-destructive phase-1 benchmark of ``meu_coding`` against a repository (default: this one).

Reads the repository only. The extraction cache goes to a temporary directory that is
deleted afterwards, and "changed" files for the refresh timings are simulated by aging
their in-memory metadata, so no file in the repository is touched. Usage::

    python scripts/meu/coding_engine_benchmark.py [ROOT] [--query TEXT] [--budget CHARS] [--deep-all]
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from meu_coding import RepositoryIntelligence
from meu_coding.cache import JsonFileCache

_DEFAULT_QUERIES = (
    "SymbolExtractor falls back when tree-sitter is missing",
    "fix approval card parsing in plugins/platforms/slack/adapter.py",
    "resolve_gateway_approval_card admin ids",
)


def _timed(label: str, fn):
    start = time.perf_counter()
    value = fn()
    elapsed = time.perf_counter() - start
    print(f"{label:<40} {elapsed:8.2f} s")
    return value


def _row(label: str, value) -> None:
    print(f"{label:<40} {value:>8}")


def _age(intel: RepositoryIntelligence, count: int) -> list[str]:
    """Make ``count`` Python files look modified, without touching them on disk."""
    files = intel.analysis.files_by_path
    paths = [p for p in sorted(files) if p.endswith(".py")][::97][:count]
    for path in paths:
        files[path] = dataclasses.replace(files[path], mtime_ns=files[path].mtime_ns - 1)
    return paths


def _cache_size(directory: Path) -> float:
    return sum(p.stat().st_size for p in directory.iterdir()) / 1e6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--query", action="append")
    parser.add_argument("--budget", type=int, default=12_000)
    parser.add_argument("--deep-all", action="store_true", help="also deep-parse every file once")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="meu-coding-bench-") as tmp:
        cache_dir = Path(tmp) / "cache"
        cold = RepositoryIntelligence(args.root, cache=JsonFileCache(cache_dir))
        _timed("initial index (cold, fast)", cold.analyze_repository)
        _row("files indexed", cold.stats.files)
        _row("files parsed", cold.stats.extracted)
        for key, value in cold.symbol_counts().items():
            _row(f"fast index {key}", value)
        _row("cache size after index (MB)", f"{_cache_size(cache_dir):.1f}")

        warm = RepositoryIntelligence(args.root, cache=JsonFileCache(cache_dir))
        _timed("cached startup", warm.analyze_repository)
        _row("cache hits", warm.stats.cache_hits)

        for count in (1, 10):
            paths = _age(warm, count)
            _timed(f"{count}-file refresh (paths given)", lambda p=paths: warm.refresh_changed_files(p))
        _age(warm, 1)
        _timed("1-file refresh (full metadata rescan)", warm.refresh_changed_files)

        for query in args.query or _DEFAULT_QUERIES:
            bundle = _timed(f"context: {query[:30]}…", lambda q=query: warm.find_relevant_context(q, args.budget))
            top = ", ".join(item.path for item in bundle.items[:3])
            print(f"    {len(bundle.items)} items, {bundle.size} chars; top: {top}")
            bundle = _timed("    same query again", lambda q=query: warm.find_relevant_context(q, args.budget))
        warm.save_cache()
        for key, value in warm.symbol_counts().items():
            _row(f"after queries {key}", value)
        _row("cache size after queries (MB)", f"{_cache_size(cache_dir):.1f}")

        if args.deep_all:
            _timed("deep-parse every file", warm.deep_analyze)
            warm.save_cache()
            for key, value in warm.symbol_counts().items():
                _row(f"all deep {key}", value)
            _row("cache size all deep (MB)", f"{_cache_size(cache_dir):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
