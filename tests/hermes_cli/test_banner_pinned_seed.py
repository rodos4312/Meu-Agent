"""A phone engine still at its seed pin never looks up a release in the background."""
import subprocess
from pathlib import Path

import pytest

from hermes_cli import banner


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "engine"
    root.mkdir()
    git = ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
           "-c", "maintenance.auto=false", "-c", "gc.auto=0"]
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "a.txt").write_bytes(b"one\n")
    subprocess.run(["git", "add", "a.txt"], cwd=root, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "seed"], cwd=root, check=True)
    return root


def _prefetch(monkeypatch, root: Path) -> list:
    calls = []
    monkeypatch.setattr(banner, "_skip_background_prefetch", lambda: False)
    monkeypatch.setattr("hermes_cli.config.get_project_root", lambda: root)
    monkeypatch.setattr(banner.source_check, "check_for_updates",
                        lambda **kw: calls.append(kw) or {"behind": 3})
    banner._update_check_done.clear()
    banner.prefetch_update_check()
    assert banner._update_check_done.wait(10)
    return calls


def test_pinned_seed_engine_skips_the_release_lookup(monkeypatch, repo):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "config", "--local", "meu.seedRevision", head], cwd=repo, check=True)
    assert _prefetch(monkeypatch, repo) == []


def test_ordinary_clone_still_checks_for_updates(monkeypatch, repo):
    assert _prefetch(monkeypatch, repo) == [{"passive": True}]
