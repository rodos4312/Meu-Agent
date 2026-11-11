"""Lightweight audit record per coding task: one JSON file under the profile's home.

Holds identifiers and decisions only — task id, project, model routes (provider:model
names), hashes and fingerprints, the approval decision, worktree identity, checks and their
status, the Reviewer verdict, keep/reject and a commit hash. Never prompts, diffs, file
contents, keys or credential payloads. Written with MEU's atomic writer.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[0-9a-f]{32}$")
SECRET_HINTS = ("api_key", "token", "secret", "password", "authorization", "credential")


def audit_dir() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()) / "coding_tasks"


@dataclass
class AuditRecord:
    task_id: str
    project: str
    description: str = ""
    created_at: float = field(default_factory=time.time)
    stages: list[dict[str, Any]] = field(default_factory=list)
    models: dict[str, str] = field(default_factory=dict)
    route_source: str = ""
    plan_hash: str = ""
    proposal_fingerprint: str = ""
    approval_id: str = ""
    approval_fingerprint: str = ""
    decisions: list[dict[str, Any]] = field(default_factory=list)
    worktree: dict[str, str] = field(default_factory=dict)
    checks: list[dict[str, str]] = field(default_factory=list)
    reviewer_verdict: str = ""
    keep_reject: str = ""
    commit_hash: str = ""
    error: str = ""
    routing: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    integration: dict[str, Any] = field(default_factory=dict)
    pr: dict[str, Any] = field(default_factory=dict)
    remote: dict[str, Any] = field(default_factory=dict)

    def stage(self, name: str) -> None:
        self.stages.append({"stage": name, "at": round(time.time(), 3)})

    def to_json(self) -> str:
        data = dict(self.__dict__)
        _assert_no_secrets(data)
        return json.dumps(data, indent=1, sort_keys=True)


def _assert_no_secrets(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if any(h in str(key).lower() for h in SECRET_HINTS):
                raise ValueError(f"audit field {path}{key} looks like a secret")
            _assert_no_secrets(item, f"{path}{key}.")
    elif isinstance(value, list):
        for item in value:
            _assert_no_secrets(item, path)


def save(record: AuditRecord, directory: Path | None = None) -> None:
    from tools.file_operations_native import atomic_write

    if not _ID.match(record.task_id):
        raise ValueError("invalid task id")
    target = (directory or audit_dir()) / f"{record.task_id}.json"
    error = atomic_write(str(target), record.to_json().encode("utf-8"))
    if error:
        raise OSError(error)


def load_all(directory: Path | None = None, limit: int = 200) -> list[AuditRecord]:
    folder = directory or audit_dir()
    if not folder.is_dir():
        return []
    records = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        if not _ID.match(path.stem):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in AuditRecord.__dataclass_fields__}
            records.append(AuditRecord(**known))
        except (OSError, ValueError, TypeError):
            continue
    return records
