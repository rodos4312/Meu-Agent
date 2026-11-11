import os

import pytest

from meu_coding.repo_index import IndexConfig, RepositoryIndexer, parse_gitignore


def _paths(root, config=None):
    return [f.path for f in RepositoryIndexer(root, config).scan()]


def test_enumerates_sources_in_sorted_posix_order(make_repo):
    root = make_repo({"b/z.py": "x = 1\n", "a.py": "y = 2\n", "b/a.ts": "let a = 1\n"})
    assert _paths(root) == ["a.py", "b/a.ts", "b/z.py"]


def test_records_language_extension_and_metadata(make_repo):
    root = make_repo({"pkg/mod.py": "print('hi')\n", "web/app.tsx": "export {}\n"})
    files = {f.path: f for f in RepositoryIndexer(root).scan()}
    mod = files["pkg/mod.py"]
    assert (mod.language, mod.extension) == ("python", ".py")
    assert mod.size == os.path.getsize(root / "pkg" / "mod.py")
    assert mod.mtime_ns == os.stat(root / "pkg" / "mod.py").st_mtime_ns
    assert files["web/app.tsx"].language == "typescript"


@pytest.mark.parametrize("ignored", [
    ".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", "coverage",
    ".cache", ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
])
def test_generated_and_tool_directories_are_skipped(make_repo, ignored):
    root = make_repo({"keep.py": "a = 1\n", f"{ignored}/inner/skip.py": "b = 2\n"})
    assert _paths(root) == ["keep.py"]


def test_binary_files_are_excluded_by_content_and_extension(make_repo):
    root = make_repo({
        "code.py": "a = 1\n", "blob.dat": b"abc\0def", "logo.png": b"\x89PNG",
    })
    assert _paths(root) == ["code.py"]


def test_gitignore_patterns_negation_and_nesting(make_repo):
    root = make_repo({
        ".gitignore": "*.log\nsecret/\n/top_only.py\n!keep.log\n",
        "a.log": "x", "keep.log": "x", "secret/s.py": "x = 1\n", "top_only.py": "x = 1\n",
        "sub/top_only.py": "x = 1\n", "sub/.gitignore": "local_*.py\n",
        "sub/local_x.py": "x = 1\n", "local_y.py": "y = 1\n",
    })
    assert _paths(root) == [".gitignore", "keep.log", "local_y.py", "sub/.gitignore", "sub/top_only.py"]


def test_gitignore_can_be_disabled(make_repo):
    root = make_repo({".gitignore": "*.py\n", "a.py": "x = 1\n"})
    assert _paths(root, IndexConfig(respect_gitignore=False)) == [".gitignore", "a.py"]


def test_include_and_exclude_rules(make_repo):
    root = make_repo({"src/a.py": "", "src/b.ts": "", "docs/c.md": "", "src/gen/d.py": ""})
    assert _paths(root, IndexConfig(include=("*.py",))) == ["src/a.py", "src/gen/d.py"]
    assert _paths(root, IndexConfig(exclude=("src/gen/*", "docs/*"))) == ["src/a.py", "src/b.ts"]


def test_oversized_files_are_skipped(make_repo):
    root = make_repo({"small.py": "a = 1\n", "huge.py": "a = 1\n" * 1000})
    assert _paths(root, IndexConfig(max_file_bytes=100)) == ["small.py"]


def test_root_must_be_an_existing_directory(tmp_path):
    with pytest.raises(NotADirectoryError):
        RepositoryIndexer(tmp_path / "missing")


def test_scan_is_read_only(make_repo):
    root = make_repo({"a.py": "a = 1\n", ".gitignore": "*.tmp\n"})
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    RepositoryIndexer(root).scan()
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_parse_gitignore_skips_comments_and_blank_lines():
    rules = parse_gitignore("# comment\n\n*.pyc\n")
    assert len(rules) == 1 and rules[0].regex.match("deep/x.pyc")
