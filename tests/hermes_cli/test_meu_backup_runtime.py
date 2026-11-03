"""Managed source belongs to Git/PM recovery, never to profile-data archives."""
from argparse import Namespace
from pathlib import Path
import zipfile

import pytest

from hermes_cli import backup


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("MEU_HOME", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("hermes_cli.gateway_setup_service.ensure_gateway_service", lambda **_kw: False)
    monkeypatch.setattr("hermes_cli.gateway._is_service_running", lambda: False)
    for profile in (root, root / "profiles" / "work"):
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "config.yaml").write_text("model: {}\n", encoding="utf-8")
        for name in ("meu-agent", "hermes-agent"):
            checkout = profile / name
            checkout.mkdir()
            # If backup descends here, the invalid DB reveals the wrong ownership.
            (checkout / "runtime.db").write_bytes(b"not a profile database")
            (checkout / "backend.py").write_text("current code", encoding="utf-8")
            nested = profile / "skills" / "sample" / name
            nested.mkdir(parents=True)
            (nested / "notes.txt").write_text("user skill data", encoding="utf-8")
    return root


def test_full_backup_prunes_both_checkout_names_but_keeps_nested_skill_data(home, tmp_path):
    archive = tmp_path / "profile.zip"
    assert backup.run_backup(Namespace(output=str(archive), keep=0))
    with zipfile.ZipFile(archive) as stream:
        names = set(stream.namelist())
    for prefix in ("", "profiles/work/"):
        for name in ("meu-agent", "hermes-agent"):
            assert not any(member.startswith(prefix + name + "/") for member in names)
            assert prefix + f"skills/sample/{name}/notes.txt" in names


def test_older_archive_cannot_overwrite_the_installed_checkout(home, tmp_path):
    archive = tmp_path / "older.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("config.yaml", "model: {}\n")
        stream.writestr("profiles/work/config.yaml", "model: {}\n")
        for prefix in ("", "profiles/work/"):
            for name in ("meu-agent", "hermes-agent"):
                stream.writestr(prefix + name + "/backend.py", "archived source must not replace current code")
                stream.writestr(prefix + f"skills/sample/{name}/notes.txt", "restored user skill")
    backup.run_import(Namespace(zipfile=str(archive), force=True))
    for profile in (home, home / "profiles" / "work"):
        for name in ("meu-agent", "hermes-agent"):
            assert (profile / name / "backend.py").read_text(encoding="utf-8-sig") == "current code"
            assert (profile / "skills" / "sample" / name / "notes.txt").read_text(encoding="utf-8-sig") == "restored user skill"
