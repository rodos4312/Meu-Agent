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
import tempfile
import zipfile

from pm.environments import selected_venv
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
    environment = selected_venv(root).resolve()
    shutil.copytree(_io_path(environment), _io_path(transaction / "environment"),
                    copy_function=_link_or_copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in HELPERS:
        shutil.copy2(Path(__file__).with_name(name), _io_path(transaction / name))
    stdlib = runtime / ("Lib" if os.name == "nt" else f"lib/python{sys.version_info.major}.{sys.version_info.minor}")
    shutil.copy2(Path(__file__).with_name("meu_recovery_bootstrap.py"), _io_path(stdlib / "meu_recovery_start.py"))
    files = {name: _hash(transaction / name) for name in HELPERS}
    io_root = _io_path(transaction)
    for directory in (source, runtime, transaction / "environment"):
        for file in _io_path(directory).rglob("*"):
            if file.is_file():
                files[file.relative_to(io_root).as_posix()] = _hash(file)
    durable_write_bytes(transaction / "payload.json", json.dumps({
        "schema": 1, "files": files,
        "locations": {"runtime": str(Path(sys.base_prefix).resolve()), "environment": str(environment)},
        "managedEnvironment": (environment.parent / ".lease-managed").is_file(),
    }).encode("utf-8"))
    durable_write_bytes(transaction / "transaction.json", json.dumps({
        **record, "payloadHash": _hash(transaction / "payload.json"),
    }).encode("utf-8"))


def verify(transaction: Path) -> None:
    record = json.loads((transaction / "transaction.json").read_text(encoding="utf-8-sig"))
    if _hash(transaction / "payload.json") != record.get("payloadHash"):
        raise ValueError("Retained recovery manifest changed")
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


def rehydrate(transaction: Path) -> None:
    """Rebuild collected immutable paths before restoring facts that select them.

    Called under the installation maintenance lock. Never overwrite different
    existing bytes: a foreign edit is a reason to stop before data rewind.
    """
    verify(transaction)
    payload = json.loads((transaction / "payload.json").read_text(encoding="utf-8-sig"))
    for prefix, original in payload["locations"].items():
        if prefix not in {"runtime", "environment"}:
            raise ValueError("Unknown retained recovery location")
        destination = Path(original)
        if not destination.is_absolute() or destination.resolve() != destination:
            raise ValueError("Retained runtime location moved outside its captured path")
        _restore_tree(transaction, prefix, destination, payload["files"])
    if payload.get("managedEnvironment"):
        marker = Path(payload["locations"]["environment"]).parent / ".lease-managed"
        if not marker.exists():
            marker.touch()


def _restore_tree(transaction: Path, prefix: str, destination: Path, files: dict) -> None:
    root = _io_path(destination)
    parents = set()
    for name, digest in files.items():
        if not name.startswith(prefix + "/") or name == "runtime/Lib/meu_recovery_start.py":
            continue  # The standalone entry point was never part of the original PM Python.
        file = root / name.removeprefix(prefix + "/")
        if file.parent not in parents:
            if not file.parent.resolve().is_relative_to(root):
                raise ValueError("Retained runtime destination leaves its captured directory")
            file.parent.mkdir(parents=True, exist_ok=True)
            parents.add(file.parent)
        if file.is_symlink():
            raise ValueError("Retained runtime file became a symbolic link: " + str(file))
        if file.exists():
            if _hash(file) != digest:
                raise ValueError("Existing runtime file differs from the retained generation: " + str(file))
        else:
            _restore_file(_io_path(transaction / name), file)


def _restore_file(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except FileExistsError:
        raise ValueError("Runtime destination appeared during recovery: " + str(destination)) from None
    except OSError:
        # A cross-volume copy must not leave half a DLL at its final name.
        staged = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".meu-restore-", delete=False) as output:
                staged = Path(output.name)
                with source.open("rb") as original:
                    shutil.copyfileobj(original, output)
                output.flush()
                os.fsync(output.fileno())
            staged.rename(destination)  # Windows refuses an existing destination; no foreign bytes replaced.
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transaction", type=Path, required=True)
    freeze(parser.parse_args().transaction)
