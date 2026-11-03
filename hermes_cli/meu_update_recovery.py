"""Local Meu update snapshots and bounded, offline rollback to the captured install.

Desktop stages this file outside the changing checkout and starts the watcher
under the OLD runtime before handoff. Existing backup/maintenance code owns
SQLite consistency, profile reservations and runtime epoch preservation.
"""
from __future__ import annotations

from argparse import Namespace
import base64
from contextlib import closing, redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sqlite3
import sys
import uuid
import zipfile
from collections.abc import Callable

from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from gateway.runtime_ownership import exclusive_maintenance
from hermes_cli import backup
from hermes_cli.profiles import profiles_to_serve
from hermes_cli.runtime_state import runtime_lock
from hermes_constants import get_default_hermes_root, reset_hermes_home_override, set_hermes_home_override
from hermes_dir_acl import make_user_dir
from pm.environments import runtime_facts_path
from pm.filesystem import durable_write_bytes

REPOSITORY = "https://github.com/rodos4312/Meu-Agent.git"
BRANCH = "dev/meu-foundation"
FIELDS = ("schema", "repository", "branch", "channel", "version", "commit",
          "publisherName", "file", "size", "sha256", "sha512")


def write_record(path: Path, value: dict) -> None:
    durable_write_bytes(path, json.dumps(value, ensure_ascii=True).encode("utf-8"))


def read_record(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Invalid Meu recovery record")
    return value


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Recovery file must be a regular file")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_release(release: dict, key: str, directory: Path) -> Path:
    """Recheck the free update signature and retained bytes before execution."""
    version = release.get("version", "")
    if (release.get("schema") != 2 or release.get("repository") != "rodos4312/Meu-Agent"
            or release.get("branch") != BRANCH or release.get("channel") != "meu-preview"
            or release.get("publisherName") != "" or not isinstance(version, str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-dev\.[0-9]+)?", version)
            or release.get("file") != f"Meu-{version}-win-x64.exe"
            or not re.fullmatch(r"[a-f0-9]{40}", str(release.get("commit", "")))
            or type(release.get("size")) is not int or not 0 < release["size"] <= 512 * 1024 * 1024):
        raise ValueError("Invalid Meu recovery release authority")
    public = load_der_public_key(base64.b64decode(key, validate=True))
    if not isinstance(public, Ed25519PublicKey):
        raise ValueError("Recovery requires the installed Ed25519 key")
    payload = ["Meu Windows update v2", *(release[field] for field in FIELDS)]
    public.verify(base64.b64decode(release["signature"], validate=True),
                  json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    installer = directory / release["file"]
    if installer.stat().st_size != release["size"] or digest(installer) != release["sha256"]:
        raise ValueError("Recovery installer bytes do not match the signed release")
    return installer


def git(root: Path, executable: str, *args: str) -> str:
    result = subprocess.run([executable, "-C", str(root), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=True,
                            timeout=120, env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
                            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    return result.stdout.strip()


def checkout_identity(root: Path, executable: str) -> str:
    if (git(root, executable, "config", "--get", "remote.origin.url").rstrip("/") != REPOSITORY
            or git(root, executable, "branch", "--show-current") not in ("", BRANCH)
            or git(root, executable, "status", "--porcelain")):
        raise ValueError("Recovery refuses a foreign branch, repository or locally edited checkout")
    return git(root, executable, "rev-parse", "HEAD")


def snapshot(path: Path) -> str:
    with redirect_stdout(sys.stderr):
        complete = backup.run_backup(Namespace(output=str(path), keep=0))
    if not complete or not path.is_file():
        raise OSError("A complete Meu recovery backup could not be created")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Meu recovery archive is damaged")
    return digest(path)


WORK_TABLES = ("session_admissions", "worker_executions", "worker_receipts", "messages",
               "delivery_obligations", "response_admissions")


def work_state(home: Path, databases: list[str], previous: dict | None = None) -> dict:
    """Never rewind work accepted after the snapshot, even if startup failed."""
    state = {}
    for name in databases:
        database = home / name
        if not database.resolve().is_relative_to(home.resolve()):
            raise ValueError("Recovery database leaves the owning home")
        tables = {}
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            for table in WORK_TABLES:
                columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
                if previous is not None:
                    before = previous[name][table]["columns"]
                    columns = before or columns
                names = ",".join('"' + value.replace('"', '""') + '"' for value in columns)
                hashed = hashlib.sha256()
                if names:
                    for row in db.execute(f'SELECT {names} FROM "{table}" ORDER BY {names}'):
                        hashed.update(repr(row).encode("utf-8"))
                        hashed.update(b"\n")
                # A previously absent empty table is harmless; new rows are not.
                tables[table] = {"columns": columns if previous is None else previous[name][table]["columns"],
                                 "digest": hashed.hexdigest()}
        state[name] = tables
    return state


def prepare(root: Path, home: Path, directory: Path, key: str, executable: str) -> Path:
    """Capture every profile and the exact PM selection, with the owner stopped."""
    journal = read_record(directory / "meu-update-recovery.json")
    for name in ("target", "rollback"):
        if not isinstance(journal.get(name), dict):
            raise ValueError("Both signed installers are required before updating")
        verify_release(journal[name], key, directory)
    current = checkout_identity(root, executable)
    source = get_default_hermes_root(home=home).resolve()
    if source != get_default_hermes_root().resolve():
        raise ValueError("Recovery home differs from the selected installation")
    homes = [entry for _name, entry in profiles_to_serve(True, include_standalone=True, include_parked=True)]
    transaction = source / "backups" / f"meu-update-{uuid.uuid4().hex}"
    make_user_dir(transaction, 0o700, parents=True)
    facts = runtime_facts_path(root)
    with exclusive_maintenance([source, *homes]), runtime_lock(root) as locked:
        if not locked:
            raise TimeoutError("The Meu dependency selection is busy; update refused")
        archive_hash = snapshot(transaction / "before.zip")
        with zipfile.ZipFile(transaction / "before.zip") as archive:
            databases = [name for name in archive.namelist() if name.endswith(".db") and not name.startswith("_external/")]
        executions = work_state(source, databases)
        facts_hash = None
        if facts.is_file():
            durable_write_bytes(transaction / "runtime-facts.json", facts.read_bytes())
            facts_hash = digest(transaction / "runtime-facts.json")
    record = {"schema": 1, "root": str(root.resolve()), "home": str(source), "sourceCommit": current,
              "git": executable, "directory": str(directory.resolve()), "key": key,
              "target": journal["target"], "rollback": journal["rollback"],
              "archiveHash": archive_hash, "factsHash": facts_hash, "workState": executions, "state": "prepared"}
    write_record(transaction / "transaction.json", record)
    return transaction


def restore(transaction: Path, *, stop_desktop: Callable[[], None] | None = None) -> dict:
    """Keep failed state first, then restore code, all profiles and dependencies."""
    record = read_record(transaction / "transaction.json")
    root, home = Path(record["root"]), Path(record["home"])
    expected = home / "backups" / transaction.name
    if (transaction.resolve() != expected.resolve() or not re.fullmatch(r"meu-update-[a-f0-9]{32}", transaction.name)
            or home.resolve() != get_default_hermes_root().resolve()):
        raise ValueError("Recovery transaction belongs to another home")
    verify_release(record["rollback"], record["key"], Path(record["directory"]))
    verify_release(record["target"], record["key"], Path(record["directory"]))
    if digest(transaction / "before.zip") != record["archiveHash"]:
        raise ValueError("Recovery backup hash mismatch")
    facts = runtime_facts_path(root)
    if record["factsHash"] and digest(transaction / "runtime-facts.json") != record["factsHash"]:
        raise ValueError("Recovery dependency record hash mismatch")
    current = checkout_identity(root, record["git"])
    if current not in (record["sourceCommit"], record["target"]["commit"]):
        raise ValueError("The installation moved after this update; automatic recovery refused")
    homes = [entry for _name, entry in profiles_to_serve(True, include_standalone=True, include_parked=True)]
    with exclusive_maintenance([home, *homes]), runtime_lock(root) as locked:
        if not locked:
            raise TimeoutError("The Meu dependency selection is busy; recovery refused")
        failed = transaction / "failed-state.zip"
        if not failed.exists():
            snapshot(failed)
        with zipfile.ZipFile(failed) as archive:
            created = {name for name in archive.namelist() if name.endswith(".db") and not name.startswith("_external/")}
        if created - set(record["workState"]):
            raise ValueError("A new database appeared after the update; automatic state rewind refused")
        if work_state(home, list(record["workState"]), record["workState"]) != record["workState"]:
            raise ValueError("New work was accepted after the update; automatic state rewind refused")
        if stop_desktop is not None:
            stop_desktop()
        # --keep refuses conflicting edits. No user branch or untracked files are removed.
        git(root, record["git"], "reset", "--keep", record["sourceCommit"])
        token = set_hermes_home_override(home)
        try:
            with redirect_stdout(sys.stderr):
                result = backup.run_import(Namespace(zipfile=str(transaction / "before.zip"), force=True))
        finally:
            reset_hermes_home_override(token)
        if result:
            raise OSError("Meu profile restore was incomplete; failed state remains preserved")
        if record["factsHash"]:
            durable_write_bytes(facts, (transaction / "runtime-facts.json").read_bytes())
    record["state"] = "restored"
    write_record(transaction / "transaction.json", record)
    return record


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--git", required=True)
    options = parser.parse_args()
    print(json.dumps({"transaction": str(prepare(options.root, options.home, options.directory, options.key, options.git))}))
