"""Bounded, profile-local versions of curated memory; never part of the model tool schema."""

from __future__ import annotations

import difflib
import json
import re
import time
import uuid
from pathlib import Path

from utils import atomic_json_write

_TARGETS = {"MEMORY.md": "memory", "USER.md": "user"}
_FILENAMES = {target: filename for filename, target in _TARGETS.items()}
_VERSION = re.compile(r"[a-f0-9]{32}\Z")
_KEEP_PER_TARGET = 50


def save_previous_memory(path: Path, content: str) -> None:
    """Called under the memory file lock, before replacement. Refuse if backup cannot be saved."""
    target = _TARGETS.get(path.name)
    if target is None:
        raise ValueError("Unknown memory file")
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    if before == content:
        return
    directory = path.parent / ".history"
    directory.mkdir(parents=True, exist_ok=True)
    record = {"id": uuid.uuid4().hex, "target": target, "created_ns": time.time_ns(), "content": before}
    atomic_json_write(directory / f"{record['id']}.json", record)
    records = [r for r in memory_versions(path.parent) if r["target"] == target]
    for old in records[_KEEP_PER_TARGET:]:
        (directory / f"{old['id']}.json").unlink()


def memory_versions(directory: Path) -> list[dict]:
    """Metadata only: listing history never exposes the text to a model or remote provider."""
    records = []
    for path in (directory / ".history").glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (isinstance(raw, dict) and _VERSION.fullmatch(str(raw.get("id", "")))
                    and path.stem == raw["id"] and raw.get("target") in _FILENAMES
                    and isinstance(raw.get("created_ns"), int) and isinstance(raw.get("content"), str)):
                records.append({key: raw[key] for key in ("id", "target", "created_ns")})
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda r: r["created_ns"], reverse=True)


def _version(directory: Path, version_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{8,32}", version_id):
        raise ValueError("Invalid memory version id")
    if len(version_id) < 32:
        matches = [r["id"] for r in memory_versions(directory) if r["id"].startswith(version_id)]
        if len(matches) != 1:
            raise ValueError("Version not found or ambiguous; use the full version id")
        version_id = matches[0]
    raw = json.loads((directory / ".history" / f"{version_id}.json").read_text(encoding="utf-8"))
    if (not isinstance(raw, dict) or raw.get("id") != version_id or raw.get("target") not in _FILENAMES
            or not isinstance(raw.get("content"), str)):
        raise ValueError("Invalid memory version")
    return raw


def memory_version_diff(directory: Path, version_id: str) -> str:
    record = _version(directory, version_id)
    path = directory / _FILENAMES[record["target"]]
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    return "".join(difflib.unified_diff(
        record["content"].splitlines(keepends=True), current.splitlines(keepends=True),
        fromfile=f"{path.name}@{version_id}", tofile=f"{path.name}@current", lineterm="\n")) or "No changes."


def restore_memory_version(store, version_id: str) -> str:
    """An explicit operator command; keep the active session's prompt snapshot frozen."""
    from tools.memory_tool import get_memory_dir
    from tools.memory_tool_store import _scan_memory_content

    directory = get_memory_dir()
    record = _version(directory, version_id)
    target, content = record["target"], record["content"]
    if error := _scan_memory_content(content):
        raise ValueError(error)
    entries = store._parse_entries(content)
    if len(content) > store._char_limit(target):
        raise ValueError("This version exceeds the current memory limit; review it before restoring")
    path = directory / _FILENAMES[target]
    with store._file_lock(path):
        store._write_file(path, entries)
        store._set_entries(target, entries)
    return f"Restored {path.name} from {version_id}. New conversations use the restored memory; the current conversation stays as it was."
