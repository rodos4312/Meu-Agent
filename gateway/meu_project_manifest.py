"""Content inventory and three-way review for a user-selected project folder."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from hermes_dir_acl import is_reparse_point

_MAX_ENTRIES = 25_000
_MAX_BYTES = 512 * 1024 * 1024
_SKIP_DIRS = frozenset({".git", ".venv", "__pycache__", "node_modules"})
_SECRET_SUFFIXES = (".key", ".p12", ".pfx", ".jks", ".keystore")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)", re.I)


@dataclass(frozen=True)
class ProjectInventory:
    files: dict[str, str]
    excluded: tuple[str, ...]


@dataclass(frozen=True)
class ProjectReview:
    additions: tuple[str, ...]
    updates: tuple[str, ...]
    deletions: tuple[str, ...]
    conflicts: tuple[str, ...]


def _path_key(path: str) -> str:
    parts = path.split("/")
    if any(not part or part in {".", ".."} or part.endswith((".", " "))
           or _WINDOWS_RESERVED.match(part)
           or any(ord(char) < 32 or char in '<>:"\\|?*' for char in part)
           for part in parts):
        raise ValueError(f"Unsupported project path: {path}")
    return unicodedata.normalize("NFC", path).casefold()


def _parents(path: str):
    while "/" in path:
        path = path.rsplit("/", 1)[0]
        yield path


def _path_index(files: dict[str, str]) -> dict[str, str]:
    indexed = {}
    for path, digest in files.items():
        key = _path_key(path)
        if key in indexed or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid or ambiguous project manifest")
        indexed[key] = path
    if any(parent in indexed for key in indexed for parent in _parents(key)):
        raise ValueError("Project manifest contains a file/directory collision")
    return indexed


def scan_project(root: Path) -> ProjectInventory:
    """Inventory regular files without following links or copying any bytes."""
    if is_reparse_point(root) or not root.is_dir():
        raise ValueError("Select a regular project folder")
    root = root.resolve(strict=True)
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ValueError("Select a project folder rather than the drive or home folder")
    files = {}
    excluded = []
    entries = total_bytes = 0

    def fail(error: OSError):
        raise error

    for current, dirs, names in os.walk(root, onerror=fail, followlinks=False):
        folder = Path(current)
        entries += len(dirs) + len(names)
        if entries > _MAX_ENTRIES:
            raise ValueError("Project contains too many entries")
        if is_reparse_point(folder) or not folder.resolve(strict=True).is_relative_to(root):
            raise ValueError("Project folder changed during scanning")
        for name in dirs[:]:
            path = folder / name
            if name.casefold() in _SKIP_DIRS or is_reparse_point(path):
                excluded.append(path.relative_to(root).as_posix())
                dirs.remove(name)
        for name in names:
            path = folder / name
            relative = path.relative_to(root).as_posix()
            label = name.casefold()
            info = path.lstat()
            if (label == ".env" or label.startswith(".env.") or label.endswith(_SECRET_SUFFIXES)
                    or is_reparse_point(path) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                excluded.append(relative)
                continue
            _path_key(relative)
            total_bytes += info.st_size
            if total_bytes > _MAX_BYTES:
                raise ValueError("Project exceeds the inventory size limit")
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if not os.path.samestat(info, opened) or not stat.S_ISREG(opened.st_mode):
                    raise ValueError("Project file changed during scanning")
                digest = hashlib.sha256()
                remaining = info.st_size
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError("Project file changed during scanning")
                    digest.update(chunk)
                    remaining -= len(chunk)
                if stream.read(1) or os.fstat(stream.fileno()).st_mtime_ns != info.st_mtime_ns:
                    raise ValueError("Project file changed during scanning")
                files[relative] = digest.hexdigest()
    _path_index(files)
    return ProjectInventory(dict(sorted(files.items())), tuple(sorted(excluded)))


def review_project_changes(base: dict[str, str], pc: dict[str, str],
                           mobile: dict[str, str]) -> ProjectReview:
    """Compare an export baseline and both replicas without modifying the PC."""
    base_keys, pc_keys, mobile_keys = (_path_index(files) for files in (base, pc, mobile))
    pc_dirs = {parent for key in pc_keys for parent in _parents(key)}
    additions, updates, deletions, conflicts = [], [], [], []
    for path in sorted(base.keys() | mobile.keys()):
        before, incoming, current = base.get(path), mobile.get(path), pc.get(path)
        if incoming == before or incoming == current:
            continue
        key = _path_key(path)
        if (current != before or any(key in index and index[key] != path
                                    for index in (base_keys, pc_keys, mobile_keys))
                or incoming is not None and (key in pc_dirs
                                             or any(parent in pc_keys for parent in _parents(key)))):
            conflicts.append(path)
        elif incoming is None:
            deletions.append(path)
        elif before is None:
            additions.append(path)
        else:
            updates.append(path)
    return ProjectReview(tuple(additions), tuple(updates), tuple(deletions), tuple(conflicts))
