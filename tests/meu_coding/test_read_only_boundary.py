"""Phase 1 is read-only: analysing a hostile repository changes nothing and runs nothing.

The repository below would leave a marker file if any of its code were imported or
executed, and process spawning is made to fail loudly for the duration of the analysis.
"""

import os
import subprocess

import pytest

from meu_coding import analyze_repository

HOSTILE = {
    "setup.py": "open('PWNED_setup', 'w').write('x')\n",
    "conftest.py": "open('PWNED_conftest', 'w').write('x')\n",
    "pkg/__init__.py": "import os\nos.system('echo PWNED > PWNED_init')\n",
    "pkg/mod.py": "from pkg import thing\n__import__('os').makedirs('PWNED_dir')\nclass Thing: pass\n",
    "web/x.js": "require('child_process').execSync('touch PWNED_js')\n",
    ".gitignore": "*.log\n",
}


def _snapshot(root):
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes())
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_analysis_never_executes_writes_or_spawns(make_repo, monkeypatch, tmp_path):
    root = make_repo(HOSTILE)
    before = _snapshot(root)

    def refuse(*args, **kwargs):
        raise AssertionError(f"meu_coding tried to spawn a process: {args!r}")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, refuse)
    monkeypatch.setattr(os, "system", refuse)
    monkeypatch.chdir(tmp_path)

    intel = analyze_repository(root)
    intel.find_relevant_context("Thing in pkg/mod.py", budget=4_000)
    intel.refresh_changed_files()

    assert _snapshot(root) == before
    assert not list(tmp_path.glob("PWNED*")) and not list(root.rglob("PWNED*"))
    assert intel.lookup_symbol("Thing")


@pytest.mark.platforms("posix")
def test_symlinks_cannot_pull_outside_files_into_the_index(make_repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("TOKEN = 1\n", encoding="utf-8")
    root = make_repo({"a.py": "x = 1\n"})
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "secret_link.py").symlink_to(outside / "secret.py")
    intel = analyze_repository(root)
    assert [f.path for f in intel.analysis.files] == ["a.py"]
