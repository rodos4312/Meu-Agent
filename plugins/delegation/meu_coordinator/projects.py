"""Profile-owned project checkpoints, using the existing filesystem lock/write primitives.

The lock spans synchronous or detached native delegation. A free lock with a saved running
task means interrupted work, never permission to replay side effects automatically.
"""
from contextlib import contextmanager
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

from hermes_dir_acl import make_user_dir
from pm.filesystem import durable_write_bytes, lock_path, retry_held
from tools.delegate_workspace import local_project_root

from .planning import validate_plan
from .routing import WORKLOADS
from .staged_reviews import expand_reviews

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Use a project/task id containing only lowercase letters, numbers, hyphens or underscores.")
    return value


def new_project(project, root, tasks):
    root = local_project_root(root)
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 100:
        raise ValueError("Supply 1 to 100 concrete project tasks.")
    if any(not isinstance(task, dict) for task in tasks):
        raise ValueError("Every project task must be an object.")
    # Validate caller ids before deriving stable internal review ids.
    for task in tasks:
        identifier(task.get("id"))
        if not isinstance(task.get("goal"), str) or not task["goal"].strip():
            raise ValueError("Every project task needs a concrete goal.")
        if task.get("workload") not in WORKLOADS:
            raise ValueError("Set workload to routine, standard, complex or vision.")
        validate_plan([task])
        dependencies = task.get("depends_on", [])
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise ValueError("depends_on must list prerequisite task ids.")
    tasks = expand_reviews(tasks)
    rows = {}
    for task in tasks:
        key = identifier(task.get("id"))
        if key in rows:
            raise ValueError("Project task ids must be unique.")
        validate_plan([task])
        stored = dict(task)
        if "review_of" in task:
            stored.update(workload="complex", tool_access="files_only")
        rows[key] = {"task": stored, "state": "pending", "attempt": 0}
    visited = set()

    def visit(key, visiting):
        if key not in rows or key in visiting:
            raise ValueError("Project has a missing dependency or dependency cycle.")
        if key in visited:
            return
        for dep in rows[key]["task"].get("depends_on", []):
            visit(dep, visiting | {key})
        visited.add(key)

    for key in rows:
        visit(key, set())
    for row in rows.values():
        target_id = row["task"].get("review_of")
        if target_id is not None and "review_of" in rows[target_id]["task"]:
            raise ValueError("Review a deliverable task, not another review.")
    return {"schema": 1, "project": identifier(project), "root": str(root.resolve()), "tasks": rows}


class Project:
    def __init__(self, file, record):
        self.file, self.record = file, record

    def save(self):
        # Windows transcript/progress readers can briefly deny the atomic rename.
        # Retain the completed checkpoint through the existing bounded hold retry.
        data = json.dumps(self.record, ensure_ascii=True).encode("utf-8")
        retry_held(lambda: durable_write_bytes(self.file, data))

    def refresh(self):
        """An acquired project lock proves no previous coordinator run still owns it."""
        for row in self.record["tasks"].values():
            if row["state"] == "running":
                row.update(state="interrupted", error="Inspect existing artifacts before an explicit retry; outcome unknown.")
            if row["state"] == "verified":
                try:
                    actual = self.artifacts(list(row.get("artifacts", {})))
                except (OSError, ValueError):
                    actual = None
                if actual != row.get("artifacts", {}):
                    row.update(state="needs_review", error="Verified artifacts changed or disappeared.")
        # Invalidate downstream acceptance even when its own files stayed unchanged.
        changed = True
        while changed:
            changed = False
            for row in self.record["tasks"].values():
                if row["state"] == "verified" and not self.dependencies_ready(row):
                    row.update(state="needs_review", error="A prerequisite needs review again.")
                    changed = True

    def dependencies_ready(self, row):
        return all(self.record["tasks"][dep]["state"] == "verified" for dep in row["task"].get("depends_on", []))

    def artifacts(self, names, *, write_paths=()):
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise ValueError("artifacts must list project-relative files.")
        root = Path(self.record["root"]).resolve()
        scopes = [root / scope.strip().replace("\\", "/") for scope in write_paths]
        has_deliverable = False
        result = {}
        for name in names:
            file = root / name
            resolved = file.resolve()
            if Path(name).is_absolute() or not resolved.is_relative_to(root) or file.is_symlink():
                raise ValueError("Verification artifacts must remain inside the project.")
            with file.open("rb") as stream:
                result[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            has_deliverable |= any(resolved.is_relative_to(scope) for scope in scopes)
        if scopes and not has_deliverable:
            raise ValueError("A writing task needs an artifact in its declared write_paths before acceptance.")
        return result

    def ready(self):
        rows = self.record["tasks"]
        unblocks = Counter(dep for row in rows.values() if row["state"] == "pending"
                           for dep in row["task"].get("depends_on", []))
        selected = []
        for key in sorted(rows, key=lambda task: -unblocks[task]):
            row = rows[key]
            if (row["state"] != "pending" or not self.dependencies_ready(row)
                    or (row["task"].get("review_stage") and row["attempt"] >= 3)):
                continue
            try:
                validate_plan([self.record["tasks"][name]["task"] for name in [*selected, key]])
            except ValueError:
                continue
            selected.append(key)
            if len(selected) == 2:
                break
        return selected

    def summary(self):
        from .progress import project_progress
        return {**self.record, "ready": self.ready(),
                "progress": project_progress(self.record),
                "project_folder_url": Path(self.record["root"]).as_uri(),
                "complete": all(row["state"] == "verified" for row in self.record["tasks"].values()),
                "verification": "parent-confirmed checks and file hashes; helper completion alone never verifies a task"}


@contextmanager
def open_project(home, project, initial=None, *, read_only=False):
    directory = Path(home) / "coordinator"
    make_user_dir(directory, 0o700, parents=True, exist_ok=True)
    file = directory / (identifier(project) + ".json")
    fd = lock_path(file.with_suffix(".lock"), timeout=0)
    if fd is None and not read_only:
        raise ValueError("This project is already running; inspect its helpers instead of starting it again.")
    try:
        if file.is_symlink():
            raise ValueError("Project state must be an owned regular file.")
        if initial is not None:
            if file.exists():
                raise ValueError("Project already exists. Resume its saved plan; do not overwrite it.")
            record = initial
        else:
            record = json.loads(file.read_text(encoding="utf-8-sig"))
        if record.get("schema") != 1 or record.get("project") != project:
            raise ValueError("Invalid coordinator project record.")
        state = Project(file, record)
        if fd is not None:
            state.refresh()
            state.save()
        yield state
    finally:
        if fd is not None:
            os.close(fd)
