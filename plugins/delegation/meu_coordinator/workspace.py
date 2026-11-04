"""Read-only projection of Coordinator checkpoints for a project workspace."""
import json
import os
from pathlib import Path

from pm.filesystem import lock_path

from .projects import identifier

_STATES = {"pending", "running", "interrupted", "needs_review", "verified", "failed"}
_MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024


def _checkpoint(file):
    identifier(file.stem)
    if not file.is_file() or file.is_symlink():
        return None
    lock = file.with_suffix(".lock")
    if lock.is_symlink():
        return None
    fd = lock_path(lock, timeout=0) if lock.is_file() else None
    try:
        with file.open("rb") as stream:
            payload = stream.read(_MAX_CHECKPOINT_BYTES + 1)
        if len(payload) > _MAX_CHECKPOINT_BYTES:
            return None
        record = json.loads(payload.decode("utf-8-sig"))
        if record.get("schema") == 1 and record.get("project") == file.stem:
            return record, fd is not None or not lock.exists()
        return None
    finally:
        if fd is not None:
            os.close(fd)


def _files(root, names):
    files = []
    for name in names:
        relative = Path(name)
        if relative.is_absolute():
            continue
        file = root / relative
        if file.is_symlink():
            continue
        path = file.resolve()
        if path.is_relative_to(root) and path.is_file():
            files.append({"name": name, "path": str(path)})
    return files


def _plan_summary(file, roots):
    snapshot = _checkpoint(file)
    if snapshot is None:
        return None
    record, idle = snapshot
    root = Path(record["root"])
    if not root.is_absolute() or (root := root.resolve()) not in roots:
        return None

    tasks = []
    for key, row in record["tasks"].items():
        status = row["state"]
        if status not in _STATES:
            continue
        if status == "running" and idle:
            status = "interrupted"
        result = (row.get("result") or {}) if status in {"needs_review", "verified", "failed"} else {}
        route = result.get("route") or {}
        tasks.append({
            "id": key,
            "goal": row["task"]["goal"],
            "state": status,
            "provider": route.get("provider"),
            "model": route.get("model") or result.get("model"),
            "artifacts": _files(root, row.get("artifacts") or {}) if status == "verified" else [],
        })
    return {
        "id": record["project"],
        "root": str(root),
        "session_id": record.get("session_id"),
        "tasks": tasks,
    }


def workspace_plans(home, paths):
    directory = Path(home) / "coordinator"
    if not directory.is_dir() or directory.is_symlink():
        return []
    roots = {Path(path).resolve() for path in paths if path and Path(path).is_absolute()}
    if not roots:
        return []
    plans = []
    for file in sorted(directory.glob("*.json")):
        try:
            plan = _plan_summary(file, roots)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
            continue  # One stale or damaged checkpoint must not hide the project's chats.
        if plan is not None:
            plans.append(plan)
    return plans
