import os

import pytest

from meu_coding import repo_index
from meu_coding import RepositoryIntelligence, analyze_repository
from meu_coding.cache import JsonFileCache, MemoryCache
from meu_coding.interfaces import DEEP, FAST

REPO = {
    "app/__init__.py": "",
    "app/engine.py": "class Engine:\n    def go(self):\n        return 1\n",
    "app/cli.py": "from app.engine import Engine\n\ndef main():\n    return Engine().go()\n",
    "README.md": "# demo\n",
}


def _touch_newer(path, text):
    stat = path.stat()
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))


class _CountingExtractor:
    """Wraps the real extractor and records every parse."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def supports(self, language):
        return self.inner.supports(language)

    def extract(self, path, source, language, depth=DEEP):
        self.calls.append((path, depth))
        return self.inner.extract(path, source, language, depth)


@pytest.fixture
def counting():
    from meu_coding.symbols import SymbolExtractor
    return _CountingExtractor(SymbolExtractor())


def test_public_api_end_to_end(make_repo):
    intel = analyze_repository(make_repo(REPO))
    assert [s.path for s in intel.lookup_symbol("Engine")] == ["app/engine.py"]
    assert intel.get_dependencies("app/cli.py") == ("app/engine.py",)
    assert intel.get_reverse_dependencies("app.engine") == ("app/cli.py",)
    bundle = intel.find_relevant_context("Engine.go returns the wrong value", budget=2_000)
    assert bundle.items[0].path == "app/engine.py"
    assert len(bundle.render()) <= 2_000


def test_startup_is_a_fast_index_and_queries_deepen_only_relevant_files(make_repo, counting):
    files = dict(REPO, **{f"other/mod_{i}.py": f"def unrelated_{i}():\n    return {i}\n" for i in range(5)})
    intel = RepositoryIntelligence(make_repo(files), extractor=counting)
    intel.analyze_repository()
    assert {depth for _, depth in counting.calls} == {FAST}
    counting.calls.clear()
    bundle = intel.find_relevant_context("`Engine` returns the wrong value")
    deepened = {path for path, depth in counting.calls if depth == DEEP}
    assert "app/engine.py" in deepened and "app/cli.py" in deepened
    assert not any(p.startswith("other/") for p in deepened)
    first = bundle.items[0]
    assert first.path == "app/engine.py" and "return 1" in first.excerpt
    assert intel.graph.referencing_files("Engine") == ("app/cli.py",)


def test_unsupported_files_are_indexed_but_not_parsed(make_repo):
    intel = analyze_repository(make_repo(REPO))
    assert intel.analysis.file("README.md") is not None
    assert intel.analysis.extractions["README.md"].backend == "none"
    assert intel.stats.extracted == 3


def test_refresh_processes_only_changed_files(make_repo, counting):
    root = make_repo(REPO)
    intel = RepositoryIntelligence(root, extractor=counting)
    intel.analyze_repository()
    counting.calls.clear()
    _touch_newer(root / "app" / "engine.py", "class Motor:\n    pass\n")
    (root / "app" / "new.py").write_text("def fresh():\n    return 2\n", encoding="utf-8")
    (root / "app" / "cli.py").unlink()
    changes = intel.refresh_changed_files()
    assert changes.added == ("app/new.py",)
    assert changes.modified == ("app/engine.py",)
    assert changes.removed == ("app/cli.py",)
    assert sorted(counting.calls) == [("app/engine.py", DEEP), ("app/new.py", DEEP)]
    assert intel.lookup_symbol("Engine") == () and intel.lookup_symbol("Motor")
    assert intel.recently_changed == {"app/engine.py", "app/new.py"}
    assert all("recently changed" in item.reasons for item in intel.rank("fresh motor"))


def test_one_changed_file_does_not_trigger_a_repository_scan(make_repo, counting, monkeypatch):
    root = make_repo(REPO)
    intel = RepositoryIntelligence(root, extractor=counting)
    intel.analyze_repository()
    counting.calls.clear()

    def no_scan(*args, **kwargs):
        raise AssertionError("a path-scoped refresh walked the whole repository")

    monkeypatch.setattr(intel.indexer, "scan", no_scan)
    _touch_newer(root / "app" / "engine.py", "class Engine:\n    def go(self):\n        return 2\n")
    changes = intel.refresh_changed_files(["app/engine.py", "app/cli.py"])
    assert changes.modified == ("app/engine.py",) and changes.added == changes.removed == ()
    assert counting.calls == [("app/engine.py", DEEP)]


def test_rescan_does_not_reopen_unchanged_files(make_repo, monkeypatch):
    root = make_repo(REPO)
    intel = analyze_repository(root)
    opened = []
    real = repo_index.is_binary
    monkeypatch.setattr(repo_index, "is_binary", lambda p: opened.append(p) or real(p))
    _touch_newer(root / "app" / "engine.py", "class Engine:\n    pass\n")
    intel.refresh_changed_files()
    assert [os.path.basename(p) for p in opened] == ["engine.py"]


def test_deleted_file_removes_its_symbols_and_edges(make_repo):
    root = make_repo(REPO)
    intel = analyze_repository(root)
    intel.deep_analyze()
    (root / "app" / "engine.py").unlink()
    intel.refresh_changed_files(["app/engine.py"])
    assert intel.lookup_symbol("Engine") == ()
    assert intel.get_dependencies("app/cli.py") == ("app/__init__.py",)  # the package is what is left
    assert not [e for e in intel.graph.edges() if "app/engine.py" in (e.source, e.target)
                or e.target.startswith("symbol:app/engine.py")]
    assert intel.graph.referencing_files("Engine") == ()


def test_new_file_is_added_incrementally_and_resolves_waiting_imports(make_repo):
    files = dict(REPO, **{"app/main.py": "from app.new import fresh\n\ndef run():\n    return fresh()\n"})
    root = make_repo(files)
    intel = analyze_repository(root)
    assert intel.get_dependencies("app/main.py") == ("app/__init__.py",)
    (root / "app" / "new.py").write_text("def fresh():\n    return 2\n", encoding="utf-8")
    assert intel.refresh_changed_files(["app/new.py"]).added == ("app/new.py",)
    assert intel.get_dependencies("app/main.py") == ("app/new.py",)
    assert intel.get_reverse_dependencies("app/new.py") == ("app/main.py",)
    assert intel.graph.referencing_files("fresh") == ("app/main.py",)


def test_graph_and_ranking_after_incremental_updates_equal_a_fresh_build(make_repo):
    files = dict(REPO, **{"app/main.py": "from app import engine\n\ndef run():\n    return engine.Engine()\n"})
    root = make_repo(files)
    intel = analyze_repository(root)
    intel.find_relevant_context("Engine go")
    _touch_newer(root / "app" / "engine.py", "class Engine:\n    def stop(self):\n        return 0\n")
    (root / "app" / "cli.py").unlink()
    (root / "app" / "extra.py").write_text("from app.engine import Engine\n\nE = Engine\n", encoding="utf-8")
    intel.refresh_changed_files()

    fresh = analyze_repository(root)
    fresh.deep_analyze(p for p, e in intel.analysis.extractions.items() if e.depth == DEEP)
    fresh.recently_changed = intel.recently_changed
    assert intel.graph.edges() == fresh.graph.edges()
    for query in ("Engine stop", "app/extra.py", "run engine", "E"):
        assert intel.rank(query, limit=None) == fresh.rank(query, limit=None)


def test_unchanged_files_come_from_the_persistent_cache(make_repo, tmp_path, counting):
    root = make_repo(REPO)
    cache_dir = tmp_path / "cache"
    first = RepositoryIntelligence(root, cache=JsonFileCache(cache_dir))
    first.analyze_repository()
    assert any(cache_dir.iterdir()) and first.stats.cache_hits == 0

    warm = RepositoryIntelligence(root, cache=JsonFileCache(cache_dir), extractor=counting)
    warm.analyze_repository()
    assert counting.calls == [] and warm.stats.cache_hits == 3

    _touch_newer(root / "app" / "engine.py", "class Turbine:\n    pass\n")
    after = RepositoryIntelligence(root, cache=JsonFileCache(cache_dir))
    after.analyze_repository()
    assert after.stats.extracted == 1
    assert after.lookup_symbol("Turbine") and after.lookup_symbol("Engine") == ()


def test_deep_results_survive_in_the_cache(make_repo, tmp_path, counting):
    root = make_repo(REPO)
    first = RepositoryIntelligence(root, cache=JsonFileCache(tmp_path / "c"))
    first.analyze_repository()
    first.deep_analyze(["app/engine.py"])
    first.save_cache()
    warm = RepositoryIntelligence(root, cache=JsonFileCache(tmp_path / "c"), extractor=counting)
    warm.analyze_repository()
    assert warm.analysis.extractions["app/engine.py"].depth == DEEP
    assert counting.calls == []


def test_cache_holds_no_source_text(make_repo, tmp_path):
    files = dict(REPO, **{"app/secretish.py": "def f():\n    return 'UNIQUE_BODY_TEXT_42'\n"})
    intel = RepositoryIntelligence(make_repo(files), cache=JsonFileCache(tmp_path / "c"))
    intel.analyze_repository()
    intel.deep_analyze()
    intel.save_cache()
    stored = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "c").iterdir())
    assert "UNIQUE_BODY_TEXT_42" not in stored and "secretish.py" in stored


def test_content_hash_catches_same_size_same_mtime_edit(make_repo):
    root = make_repo(REPO)
    target = root / "app" / "engine.py"
    intel = RepositoryIntelligence(root, cache=MemoryCache(verify_content=True))
    intel.analyze_repository()
    stat = target.stat()
    target.write_text(target.read_text(encoding="utf-8").replace("Engine", "Wobble"), encoding="utf-8")
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    intel.analyze_repository()
    assert intel.lookup_symbol("Wobble")


def test_corrupt_cache_shard_degrades_to_a_cold_scan(make_repo, tmp_path):
    cache_dir = tmp_path / "c"
    cache_dir.mkdir()
    for shard in range(64):
        (cache_dir / f"symbols-{shard:03d}.json").write_text("{not json", encoding="utf-8")
    intel = RepositoryIntelligence(make_repo(REPO), cache=JsonFileCache(cache_dir))
    intel.analyze_repository()
    assert intel.stats.extracted == 3 and intel.lookup_symbol("Engine")


def test_failing_cache_never_breaks_analysis(make_repo):
    class Broken(MemoryCache):
        def get(self, *args):
            raise RuntimeError("disk on fire")

        def put(self, *args):
            raise RuntimeError("disk on fire")

        def known_files(self):
            raise RuntimeError("disk on fire")

    intel = RepositoryIntelligence(make_repo(REPO), cache=Broken())
    intel.analyze_repository()
    intel.refresh_changed_files()
    assert intel.lookup_symbol("Engine")
