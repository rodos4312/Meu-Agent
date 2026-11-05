"""Portable workspace IDs; note contents and history stay in their existing profile directory."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

from hermes_dir_acl import make_user_dir
from pm.filesystem import durable_write_bytes, lock_path

MARKER = Path(".meu") / "project-memory.json"
_ID = re.compile(r"[a-f0-9]{24}")
_TOKEN = re.compile(r"[a-f0-9]{64}")


def _regular(path):
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("Project memory identity cannot follow a symbolic link or junction.")


def _read(path, limit):
    _regular(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except FileNotFoundError:
        return None
    if len(raw) > limit:
        raise ValueError("Project memory identity exceeds its size limit.")
    return json.loads(raw.decode("utf-8-sig"))


def _marker(root):
    _regular(root / MARKER.parent)
    value = _read(root / MARKER, 4096)
    if value is not None and (not isinstance(value, dict) or value.get("schema") != 1
                              or not _ID.fullmatch(str(value.get("id", "")))
                              or not _TOKEN.fullmatch(str(value.get("token", "")))):
        raise ValueError("Unrecognized project memory marker; it was not replaced.")
    return value


def _records(path):
    value = _read(path, 2 * 1024 * 1024)
    if value is None:
        return {}
    if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("records"), dict):
        raise ValueError("Invalid project memory identity index; no notes were moved.")
    for key, entry in value["records"].items():
        if (not _ID.fullmatch(key) or not isinstance(entry, dict)
                or not _TOKEN.fullmatch(str(entry.get("token", "")))
                or not isinstance(entry.get("root"), str) or not Path(entry["root"]).is_absolute()):
            raise ValueError("Invalid project memory identity record; no notes were moved.")
    return value["records"]


@contextmanager
def _locked(path):
    _regular(path)
    fd = lock_path(path, timeout=5)
    if fd is None:
        raise OSError("Project memory identity is busy; retry after the current write finishes.")
    try:
        yield
    finally:
        os.close(fd)


def _same_marker(root, marker):
    try:
        old = _marker(root)
        return old is not None and old["id"] == marker["id"] and old["token"] == marker["token"]
    except (OSError, ValueError):
        # Unknown ownership is not evidence that the old project disappeared.
        return True


def _choose(root, home, legacy, project, marker, records):
    if project:
        for key, entry in records.items():
            if entry.get("project") == project:
                return key, entry["token"], True
    if marker is None:
        for key, entry in records.items():
            if Path(entry["root"]) == root:
                return key, entry["token"], True
    if marker:
        entry = records.get(marker["id"])
        if entry and entry["token"] == marker["token"]:
            old = Path(entry["root"])
            if old == root or not _same_marker(old, marker):
                return marker["id"], marker["token"], True
        elif entry is None and (marker["id"] == legacy or not (home / "memories/projects" / marker["id"] / "PROJECT.md").exists()):
            # Another profile may adopt the portable ID only into an empty store.
            return marker["id"], marker["token"], True
    key = legacy
    while (entry := records.get(key)) and Path(entry["root"]) != root:
        # A moved project's old path may be reused. Never reuse its note store.
        key = hashlib.sha256((str(root) + key + entry["token"]).encode()).hexdigest()[:24]
    token = entry["token"] if entry else secrets.token_hex(32)
    return key, token, False


def identity_directory(root, home, legacy, project=None, *, create=False):
    """Anchor only existing notes, an existing portable identity, or an explicit note write.

    A copied live workspace is a new project. A moved workspace keeps its note
    directory. The opaque marker carries no notes, profile name or credentials.
    """
    parent = home / "memories"
    index = parent / "project-identities.json"
    records = _records(index)
    marker = _marker(root)
    key, token, adopted = _choose(root, home, legacy, project, marker, records)
    legacy_notes = home / "memories/projects" / key / "PROJECT.md"
    if not (create or adopted or legacy_notes.is_file()):
        return home / "memories/projects" / key
    make_user_dir(parent, 0o700, parents=True, exist_ok=True)
    with _locked(index.with_suffix(".lock")):
        metadata = root / MARKER.parent
        _regular(metadata)
        metadata.mkdir(exist_ok=True)
        with _locked(metadata / "project-memory.lock"):
            records, marker = _records(index), _marker(root)
            key, token, adopted = _choose(root, home, legacy, project, marker, records)
            legacy_notes = home / "memories/projects" / key / "PROJECT.md"
            if not (create or adopted or legacy_notes.is_file()):
                return home / "memories/projects" / key
            previous = records.get(key, {})
            entry = {"root": str(root), "token": token,
                     **({"project": project} if project else
                        {"project": previous["project"]} if previous.get("project") else {})}
            if entry != previous:
                records[key] = entry
                encoded = json.dumps({"schema": 1, "records": records}).encode()
                if len(encoded) > 2 * 1024 * 1024:
                    raise ValueError("Project memory identity index is full; no notes were moved.")
                durable_write_bytes(index, encoded)
            value = {"schema": 1, "id": key, "token": token}
            if marker != value:
                # Never overwrite a different live project's marker when an operator
                # changes the primary folder of a registered multi-folder project.
                conflict = marker and marker["id"] != key and adopted
                if not conflict:
                    durable_write_bytes(root / MARKER, json.dumps(value).encode())
    return home / "memories/projects" / key
