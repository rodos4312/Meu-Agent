#!/usr/bin/env python3
"""Relevance benchmark of the Meu Coding Engine on MEU's own repository.

Compares structural-only (Phase 1), semantic-only and hybrid (Phase 7) ranking on a fixed set
of realistic questions with expected files, and measures the semantic layer's cost: initial
index, cached startup, 1-file and 10-file refresh, query latency and storage size.

    python scripts/meu_coding_semantic_benchmark.py [--repo PATH] [--store DIR] [--provider local]

Read-only for the repository (it touches mtimes of nothing; refresh timings re-read files whose
metadata it rewinds in memory). The store goes to ``--store`` (default: a temporary directory).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BENCHMARK = [
    ("Where is Android reconnect handled?",
     {"apps/android/src/io/meuagent/preview/MainActivity.java", "apps/android/src/io/meuagent/preview/MeuClient.java"}),
    ("Where is coding approval fingerprint validated?",
     {"meu_coding/safe_execution.py"}),
    ("Where is worktree cleanup decided?", {"meu_coding/workspace.py", "tools/subagent_worktree.py"}),
    ("Where is DeepSeek workload routing selected?", {"agent/workload_routes.py", "meu_coding/routing_policy.py"}),
    ("Where is mobile PC status synchronized?",
     {"gateway/mobile_coding.py", "apps/android/src/io/meuagent/preview/MainActivity.java"}),
    ("Where are semantic chunks re-embedded after a file change?",
     {"meu_coding/semantic_index.py", "meu_coding/intelligence.py"}),
]
# Exact structural evidence must keep winning: (query, the file that must stay first).
EXACT = [("change resolve_workloads in meu_coding/routing_policy.py", "meu_coding/routing_policy.py"),
         ("fix decide_coder_workload escalation", "meu_coding/routing_policy.py")]
K = 10


def _metrics(paths: list[str], expected: set[str]) -> tuple[float, float]:
    top = paths[:K]
    recall = len(expected & set(top)) / len(expected)
    rank = next((i + 1 for i, p in enumerate(top) if p in expected), None)
    return recall, (1.0 / rank if rank else 0.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--store", default="")
    parser.add_argument("--provider", default="local")
    args = parser.parse_args(argv)

    from meu_coding.embeddings import resolve_embedding_provider
    from meu_coding.intelligence import RepositoryIntelligence
    from meu_coding.semantic_index import SemanticIndex, SemanticLayer
    from meu_coding.semantic_search import layer_search

    store_dir = Path(args.store or tempfile.mkdtemp(prefix="meu-semantic-bench-"))
    store = store_dir / "bench.sqlite"
    choice = resolve_embedding_provider({"coding_engine": {"semantic": {"provider": args.provider}}})
    if choice.provider is None:
        print(json.dumps({"error": choice.reason}))
        return 1
    out: dict = {"provider": choice.provider.identity.label, "repo": args.repo}

    started = time.perf_counter()
    structural = RepositoryIntelligence(args.repo)
    structural.analyze_repository()
    out["structural_index_s"] = round(time.perf_counter() - started, 2)
    out["files"] = len(structural.analysis.files_by_path)

    started = time.perf_counter()
    layer = SemanticLayer(SemanticIndex(args.repo, choice.provider, store), "enabled", choice.reason)
    hybrid = RepositoryIntelligence(args.repo, semantic=layer)
    hybrid.analyze_repository()
    out["initial_semantic_index_s"] = round(time.perf_counter() - started, 2)
    out["semantic_status"] = layer.status
    out["chunks"] = layer.index.counts()["chunks"]
    out["skipped"] = {"files": layer.index.stats.skipped_files, "chunks": layer.index.stats.skipped_chunks}

    started = time.perf_counter()
    warm = RepositoryIntelligence(args.repo, semantic=SemanticLayer(SemanticIndex(args.repo, choice.provider, store),
                                                                     "enabled", choice.reason))
    warm.analyze_repository()
    out["cached_startup_s"] = round(time.perf_counter() - started, 2)
    out["cached_startup_embedded"] = warm.semantic.index.stats.embedded

    files = sorted(p for p in warm.analysis.files_by_path if p.startswith("meu_coding/") and p.endswith(".py"))
    for label, count in (("refresh_1_file_s", 1), ("refresh_10_files_s", 10)):
        chosen = files[:count]
        for path in chosen:  # forget the stored hash so these files count as changed content
            warm.semantic.index._db.execute("UPDATE files SET source_hash = 'stale' WHERE path = ?", (path,))
        warm.semantic.index._db.commit()
        started = time.perf_counter()
        warm.semantic.update_files(warm.root, [warm.analysis.files_by_path[p] for p in chosen],
                                   warm.analysis.extractions)
        out[label] = round(time.perf_counter() - started, 3)
        out[label.replace("_s", "_embedded")] = warm.semantic.index.stats.embedded

    rows, latencies = [], []
    for query, expected in BENCHMARK:
        struct_paths = [r.path for r in structural.rank(query, limit=K)]
        t = time.perf_counter()
        hits = layer_search(warm.semantic, query, K)
        latencies.append(time.perf_counter() - t)
        semantic_paths = [h.path for h in hits]
        hybrid_paths = [r.path for r in warm.rank(query, limit=K)]
        rows.append({"query": query, "structural": _metrics(struct_paths, expected),
                     "semantic": _metrics(semantic_paths, expected), "hybrid": _metrics(hybrid_paths, expected)})
    out["queries"] = rows
    for mode in ("structural", "semantic", "hybrid"):
        out[f"{mode}_mean_recall@{K}"] = round(statistics.mean(r[mode][0] for r in rows), 3)
        out[f"{mode}_mrr"] = round(statistics.mean(r[mode][1] for r in rows), 3)
    out["exact_kept_first"] = {q: warm.rank(q, limit=3)[0].path == f for q, f in EXACT}
    out["query_latency_ms_median"] = round(statistics.median(latencies) * 1000, 1)
    out["query_latency_ms_max"] = round(max(latencies) * 1000, 1)
    out["storage_mb"] = round(store.stat().st_size / 1_048_576, 2)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
