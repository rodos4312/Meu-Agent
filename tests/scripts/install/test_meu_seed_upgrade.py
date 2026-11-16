"""Native PowerShell source-seed install/upgrade without GitHub authentication."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest

from hermes_platform.resolver import locate_command
from scripts.bundles.meu_source_seed import BRANCH, stage


@pytest.mark.platforms("windows")
@pytest.mark.parametrize("repository", ["https://github.com/rodos4312/Meu-Agent.git", "https://github.com/rodos4312/Meu-Agent-RC-private.git"])
def test_local_seed_fresh_upgrade_busy_corruption_and_user_data(tmp_path, repository):
    source, root, home = (tmp_path / name for name in ("source", "installed", "home"))
    source.mkdir(); home.mkdir()
    def git(where, *args):
        return subprocess.check_output(["git", "-C", str(where), *args], text=True).strip()
    git(source, "init", "-b", BRANCH)
    git(source, "config", "user.name", "Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    (source / "core.py").write_text("old")
    git(source, "add", "."); git(source, "commit", "-m", "old")
    old = git(source, "rev-parse", "HEAD")
    subprocess.run(["git", "clone", str(source), str(root)], check=True)
    git(root, "remote", "set-url", "origin", "https://github.com/rodos4312/Meu-Agent-RC-private.git")
    (source / "core.py").write_text("new")
    git(source, "commit", "-am", "new")
    manifest = stage(source, tmp_path / "package", old, repository=repository)
    # Real profile-like data, including a SQLite conversation and a project.
    with sqlite3.connect(home / "state.db") as database:
        database.execute("CREATE TABLE messages (content TEXT)")
        database.execute("INSERT INTO messages VALUES ('existing conversation')")
    for name in ("config.yaml", "pairing.json", "workspaces/game/index.html"):
        path = home / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep " + name)
    def personal_files():
        return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in home.rglob("*") if p.is_file() and "cache" not in p.parts}
    before = personal_files()
    installer = Path(__file__).resolve().parents[3] / "scripts/install.ps1"
    probe = tmp_path / "probe.ps1"
    probe.write_text('''param($Installer,$Root,$HomeRoot,$Seed,$Hash,$Pin,$Repository,[switch]$Busy,[switch]$Fresh,[switch]$BackupFails)
. $Installer -InstallDir $Root -HermesHome $HomeRoot -Commit $Pin -SourceSeed $Seed -SourceSeedSha256 $Hash -SourceSeedRepository $Repository -BackendOnly
function Invoke-InstalledHermes { param([string[]]$CommandArgs)
    if ($Busy) { throw 'active agent: stop refused' }
    if ($CommandArgs[0] -eq 'backup') {
        if ($BackupFails) { throw 'backup failed: upgrade refused' }
        return
    }
    if (($CommandArgs -join ' ') -ne 'gateway stop') { throw 'Unexpected lifecycle request' }
}
function Ensure-Git { return $true }
if ($Fresh) { Stage-Repository } else { Update-MeuPinnedCheckout }
''', encoding="utf-8")
    shell = locate_command("powershell")
    assert shell.found
    seed = tmp_path / "package/meu-source-seed.zip"
    def run(destination=root, *flags, checksum=manifest["sha256"]):
        return subprocess.run([*shell.command, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(probe), "-Installer", str(installer), "-Root", str(destination), "-HomeRoot", str(home),
            "-Seed", str(seed), "-Hash", checksum, "-Pin", manifest["commit"], "-Repository", repository, *flags],
            env=dict(os.environ, MEU_AGENT_MODE="1", HERMES_HOME=str(home)),
            capture_output=True, text=True, timeout=90, check=False)
    assert run(root, "-Busy").returncode != 0
    assert git(root, "rev-parse", "HEAD") == old
    assert run(root, "-BackupFails").returncode != 0
    assert git(root, "rev-parse", "HEAD") == old
    assert run(checksum="0" * 64).returncode != 0
    assert git(root, "rev-parse", "HEAD") == old
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(root, "rev-parse", "HEAD") == manifest["commit"]
    assert personal_files() == before
    fresh = tmp_path / "fresh"
    result = run(fresh, "-Fresh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(fresh, "rev-parse", "HEAD") == manifest["commit"]
    assert git(fresh, "config", "--get", "remote.origin.url") == manifest["repository"]
    assert personal_files() == before
