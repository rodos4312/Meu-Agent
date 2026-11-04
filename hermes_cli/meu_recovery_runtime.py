"""Retain an offline recovery interpreter, dependencies and pre-update source.

Published PM generations are immutable: hard links keep their bytes alive even
after collection. Source comes from the verified Git commit, never a live copy.
No credentials or process environment are persisted in this bundle.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

from pm.environments import selected_venv, site_packages
from pm.filesystem import durable_write_bytes

HELPERS = ("meu_update_recovery.py", "meu_update_watch.py", "meu_recovery_runtime.py",
           "meu_recovery_resume.py", "meu_recovery_bootstrap.py", "meu_recovery_windows.py")


def _link_or_copy(source, destination):
    try:
        os.link(source, destination)
        return destination
    except OSError:
        return shutil.copy2(source, destination)


def _hash(file: Path) -> str:
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _io_path(path: Path) -> Path:
    value = str(path.resolve())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return Path(value)


def freeze(transaction: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("The retained desktop recovery runtime is Windows-only")
    record = json.loads((transaction / "transaction.json").read_text(encoding="utf-8-sig"))
    if record["state"] != "prepared":
        raise ValueError("Freeze the recovery runtime before native handoff")
    root = Path(record["root"])
    source = transaction / "source"
    archive = transaction / "source.zip"
    subprocess.run([record["git"], "-C", str(root), "archive", "--format=zip", "--output", str(archive),
                    record["sourceCommit"], "--", "*.py", "*.json", "*.yaml", "*.yml", "*.toml", "uv.lock", "LICENSE"],
                   check=True, timeout=120,
                   **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not (source / name).resolve().is_relative_to(source.resolve()):
                raise ValueError("Recovery source archive leaves its directory")
        bundle.extractall(_io_path(source))
    archive.unlink()
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages", ".git")
    runtime = transaction / "runtime"
    shutil.copytree(_io_path(Path(sys.base_prefix)), _io_path(runtime), copy_function=_link_or_copy, ignore=ignore)
    shutil.copytree(_io_path(site_packages(selected_venv(root))), _io_path(transaction / "dependencies"),
                    copy_function=_link_or_copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in HELPERS:
        shutil.copy2(Path(__file__).with_name(name), _io_path(transaction / name))
    stdlib = runtime / ("Lib" if os.name == "nt" else f"lib/python{sys.version_info.major}.{sys.version_info.minor}")
    shutil.copy2(Path(__file__).with_name("meu_recovery_bootstrap.py"), _io_path(stdlib / "meu_recovery_start.py"))
    files = {name: _hash(transaction / name) for name in HELPERS}
    io_root = _io_path(transaction)
    for directory in (source, runtime, transaction / "dependencies"):
        for file in _io_path(directory).rglob("*"):
            if file.is_file():
                files[file.relative_to(io_root).as_posix()] = _hash(file)
    durable_write_bytes(transaction / "payload.json", json.dumps({"schema": 1, "files": files}).encode("utf-8"))


def verify(transaction: Path) -> None:
    payload = json.loads((transaction / "payload.json").read_text(encoding="utf-8-sig"))
    if payload.get("schema") != 1 or not payload.get("files"):
        raise ValueError("Invalid retained recovery payload")
    io_root = _io_path(transaction)
    parents = set()
    for name, digest in payload["files"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
            raise ValueError("Retained recovery payload leaves its directory")
        file = io_root / name
        if file.parent not in parents:
            if not file.parent.resolve().is_relative_to(io_root):
                raise ValueError("Retained recovery payload leaves its directory")
            parents.add(file.parent)
        if file.is_symlink() or _hash(file) != digest:
            raise ValueError("Retained recovery payload changed: " + name)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transaction", type=Path, required=True)
    freeze(parser.parse_args().transaction)
