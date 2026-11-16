"""Real Git cloning/fetching from the small installer, without GitHub access."""
import json
from pathlib import Path
import subprocess
import zipfile

from scripts.bundles.meu_source_seed import BRANCH, stage


def test_original_commit_history_and_source_survive_offline_seed(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    def git(root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    git(source, "init", "-b", BRANCH)
    git(source, "config", "user.name", "Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    pins = []
    for version in ("excluded upstream", "supported base", "new core"):
        (source / "runtime.py").write_text(version)
        (source / "unchanged.txt").write_text("shared file")
        git(source, "add", ".")
        git(source, "commit", "-m", version)
        pins.append(git(source, "rev-parse", "HEAD"))
    existing = tmp_path / "existing"
    subprocess.run(["git", "clone", str(source), str(existing)], check=True)
    git(existing, "reset", "--hard", pins[1])
    manifest = stage(source, tmp_path / "package", pins[1])
    assert manifest["commit"] == pins[2]
    assert json.loads((tmp_path / "package/meu-source-seed.json").read_text()) == manifest
    expanded = tmp_path / "expanded"
    with zipfile.ZipFile(tmp_path / "package/meu-source-seed.zip") as archive:
        archive.extractall(expanded)
        assert not any("hooks" in name or "credentials" in name for name in archive.namelist())
    bare = expanded / "source.git"
    git(bare, "fsck", "--full", "--strict")
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "--no-local", bare.as_uri(), str(fresh)], check=True)
    assert git(fresh, "rev-parse", "HEAD") == pins[2]
    assert (fresh / "runtime.py").read_text() == "new core"
    assert (fresh / "unchanged.txt").read_text() == "shared file"
    assert git(fresh, "rev-list", "--count", "HEAD") == "2"
    git(existing, "fetch", "--no-tags", str(bare), "refs/heads/" + BRANCH)
    git(existing, "merge-base", "--is-ancestor", "HEAD", pins[2])
    git(existing, "merge", "--ff-only", pins[2])
    assert git(existing, "rev-parse", "HEAD") == pins[2]
    assert git(existing, "rev-list", "--count", "HEAD") == "3"
