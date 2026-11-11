"""Strict schemas for model responses (Architect, Coder, Reviewer).

A model response is untrusted text. It becomes data only after :func:`parse_json_object`
and one of the ``validate_*`` functions accept it; anything else is a :class:`SchemaError`
(a controlled failure, never a guess). Models cannot express commands, approvals or
executable steps: keys that try to are rejected wherever they appear, paths must be
repository-relative and plain, and checks are logical kinds whose commands are built later
by the trusted command policy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from meu_coding.coding_interfaces import (
    CheckKind,
    EditAction,
    EditOperation,
    EditStrategy,
    FindingCategory,
    ReviewFinding,
    ReviewStatus,
    RiskLevel,
)
from meu_coding.scope import path_problem

MAX_RESPONSE_CHARS = 400_000
MAX_ITEMS = 64
MAX_TEXT = 20_000
# Keys a model must never use to steer execution, approval or the shell.
FORBIDDEN_KEYS = frozenset({
    "command", "commands", "cmd", "shell", "script", "exec", "execute", "run", "argv",
    "approved", "approval", "approve", "approver", "auto_approve", "fingerprint", "approval_id",
    "sudo", "env", "environment",
})
_UNSAFE_PATH_CHARS = re.compile(r"[\x00-\x1f\x7f$`|;&<>*?\"']")
_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n```\s*$", re.DOTALL)
MODEL_CHECK_KINDS = frozenset({CheckKind.SYNTAX, CheckKind.LINT, CheckKind.UNIT_TEST, CheckKind.BUILD})


class SchemaError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)


def safe_path_problem(path: Any) -> str | None:
    """Phase 2 path rules plus characters a path never needs (shell metacharacters,
    control characters, quotes, globs)."""
    if not isinstance(path, str):
        return f"path must be a string, got {type(path).__name__}"
    if _UNSAFE_PATH_CHARS.search(path):
        return f"{path!r} contains characters not allowed in a path"
    return path_problem(path)


def parse_json_object(text: Any) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise SchemaError(["empty response"])
    if len(text) > MAX_RESPONSE_CHARS:
        raise SchemaError([f"response longer than {MAX_RESPONSE_CHARS} characters"])
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()
    if not body.startswith("{"):
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            raise SchemaError(["response contains no JSON object"])
        body = body[start:end + 1]
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SchemaError([f"invalid JSON: {exc.msg} at line {exc.lineno}"]) from None
    if not isinstance(data, dict):
        raise SchemaError(["top-level JSON value must be an object"])
    forbidden = sorted(_forbidden_keys(data))
    if forbidden:
        raise SchemaError([f"forbidden keys in response: {forbidden}"])
    return data


def _forbidden_keys(value: Any, depth: int = 0) -> set[str]:
    if depth > 8:
        return {"<nesting too deep>"}
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                found.add(str(key))
            found |= _forbidden_keys(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            found |= _forbidden_keys(item, depth + 1)
    return found


# ── field readers: each appends to ``errors`` instead of guessing ────────────


def _text(data: dict, key: str, errors: list[str], required: bool = True, default: str = "") -> str:
    value = data.get(key)
    if value is None:
        if required:
            errors.append(f"missing field {key!r}")
        return default
    if not isinstance(value, str):
        errors.append(f"{key!r} must be a string")
        return default
    if len(value) > MAX_TEXT:
        errors.append(f"{key!r} is too long")
        return default
    return value


def _strings(data: dict, key: str, errors: list[str], required: bool = False) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        if required:
            errors.append(f"missing field {key!r}")
        return ()
    if not isinstance(value, list) or len(value) > MAX_ITEMS or not all(isinstance(v, str) for v in value):
        errors.append(f"{key!r} must be a list of at most {MAX_ITEMS} strings")
        return ()
    return tuple(value)


def _paths(data: dict, key: str, errors: list[str], required: bool = False) -> tuple[str, ...]:
    paths = _strings(data, key, errors, required)
    for path in paths:
        problem = safe_path_problem(path)
        if problem:
            errors.append(f"{key}: {problem}")
    return tuple(dict.fromkeys(paths))


def _enum(enum_type, value: Any, key: str, errors: list[str]):
    try:
        return enum_type(str(value).lower())
    except ValueError:
        errors.append(f"{key!r} must be one of {[e.value for e in enum_type]}, got {value!r}")
        return None


# ── Architect ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArchitectResponse:
    summary: str
    files_to_change: tuple[str, ...]
    new_files: tuple[str, ...]
    symbols_to_change: tuple[str, ...]
    steps: tuple[str, ...]
    checks: tuple[tuple[CheckKind, tuple[str, ...]], ...]
    assumptions: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    risk: RiskLevel


def _checks(data: dict, errors: list[str]) -> tuple[tuple[CheckKind, tuple[str, ...]], ...]:
    raw = data.get("checks", [])
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        errors.append("'checks' must be a list")
        return ()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            errors.append("each check must be an object with 'kind' and 'targets'")
            continue
        kind = _enum(CheckKind, item.get("kind"), "checks.kind", errors)
        if kind is not None and kind not in MODEL_CHECK_KINDS:
            errors.append(f"check kind {kind.value!r} cannot be requested by a model")
            continue
        targets = _paths(item, "targets", errors)
        if kind is not None:
            out.append((kind, targets))
    return tuple(out)


def validate_architect(data: dict[str, Any]) -> ArchitectResponse:
    errors: list[str] = []
    response = ArchitectResponse(
        summary=_text(data, "summary", errors),
        files_to_change=_paths(data, "files_to_change", errors, required=True),
        new_files=_paths(data, "new_files", errors),
        symbols_to_change=_strings(data, "symbols_to_change", errors),
        steps=_strings(data, "steps", errors, required=True),
        checks=_checks(data, errors),
        assumptions=_strings(data, "assumptions", errors),
        unresolved_questions=_strings(data, "unresolved_questions", errors),
        risk=_enum(RiskLevel, data.get("risk", "low"), "risk", errors) or RiskLevel.HIGH,
    )
    if errors:
        raise SchemaError(errors)
    return response


# ── Coder ───────────────────────────────────────────────────────────────────

_PAYLOAD_KEYS = {
    EditStrategy.SEARCH_REPLACE: ("search", "replace"),
    EditStrategy.WHOLE_FILE: ("content",),
    EditStrategy.V4A_PATCH: ("patch",),
    EditStrategy.UNIFIED_DIFF: ("patch",),
}


@dataclass(frozen=True)
class CoderResponse:
    operations: tuple[EditOperation, ...]
    assumptions: tuple[str, ...]
    expected_tests: tuple[str, ...]
    notes: str


def _operation(item: Any, strategy: EditStrategy, errors: list[str]) -> EditOperation | None:
    if not isinstance(item, dict):
        errors.append("each operation must be an object")
        return None
    local: list[str] = []
    path = _text(item, "path", local)
    problem = safe_path_problem(path) if path else None
    if problem:
        local.append(problem)
    action = _enum(EditAction, item.get("action", "update"), "action", local)
    if action == EditAction.DELETE:
        local.append(f"{path}: deleting files is not supported by the Coding Engine")
    op_strategy = EditStrategy.WHOLE_FILE if action == EditAction.CREATE else strategy
    payload = {}
    for key in _PAYLOAD_KEYS[op_strategy]:
        value = item.get(key)
        if not isinstance(value, str):
            local.append(f"{path}: {op_strategy.value} edit needs a string {key!r}")
        payload[key] = value
    description = _text(item, "description", local, required=False, default="")[:500]
    errors.extend(local)
    if local:
        return None
    return EditOperation(path, op_strategy, description or f"edit {path}", action, **payload)


def validate_coder(data: dict[str, Any], strategy: EditStrategy) -> CoderResponse:
    errors: list[str] = []
    raw = data.get("operations")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ITEMS:
        errors.append("'operations' must be a non-empty list")
        raw = []
    operations = [op for item in raw if (op := _operation(item, strategy, errors)) is not None]
    response = CoderResponse(
        operations=tuple(operations),
        assumptions=_strings(data, "assumptions", errors),
        expected_tests=_paths(data, "expected_tests", errors),
        notes=_text(data, "notes", errors, required=False)[:2_000],
    )
    if errors:
        raise SchemaError(errors)
    return response


# ── Reviewer ────────────────────────────────────────────────────────────────


def validate_reviewer(data: dict[str, Any]) -> tuple[ReviewFinding, ...]:
    """Findings only. A model's overall verdict is advisory: a 'fix'/'block' verdict without
    findings becomes one finding; a 'pass' verdict grants nothing."""
    errors: list[str] = []
    verdict = _enum(ReviewStatus, data.get("verdict"), "verdict", errors)
    raw = data.get("findings", [])
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        errors.append("'findings' must be a list")
        raw = []
    findings = []
    for item in raw:
        if not isinstance(item, dict):
            errors.append("each finding must be an object")
            continue
        category = _enum(FindingCategory, item.get("category", "correctness"), "category", errors)
        severity = _enum(ReviewStatus, item.get("severity"), "severity", errors)
        message = _text(item, "message", errors)[:2_000]
        path = item.get("path")
        if path is not None and safe_path_problem(path):
            errors.append(f"finding path: {safe_path_problem(path)}")
            path = None
        repair = _text(item, "repair", errors, required=False)[:2_000] or None
        if category and severity:
            findings.append(ReviewFinding(category, severity, message, path, repair))
    if errors:
        raise SchemaError(errors)
    if verdict in (ReviewStatus.FIX, ReviewStatus.BLOCK) and not any(f.severity == verdict for f in findings):
        findings.append(ReviewFinding(FindingCategory.CORRECTNESS, verdict, f"model review verdict: {verdict.value}"))
    return tuple(findings)
