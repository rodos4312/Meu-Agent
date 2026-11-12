"""Optional, justified delegation for the Coding Engine — without a new agent framework.

Two kinds of delegated unit exist, both on infrastructure MEU already has:

- **Read-only investigation** (investigate test failures, inspect one subsystem, compare two
  options, read-only research) runs in-process on the cached ``RepositoryIntelligence``:
  ranking, dependency and test relations, symbol lookups. It cannot write anything: it holds no
  file, git or approval handle.
- **Patch candidate**: an ordinary coding task (``CodingTaskService.start``) on the named files,
  i.e. the existing isolated worktree, Reviewer and explicit user approval. It is never applied,
  approved, pushed or merged by delegation.

LLM subagents through ``tools.delegate_tool.delegate_task`` are deliberately not used here: their
tool scope is decided by the delegation backend, not by this caller, so a read-only guarantee
could not be enforced from the Coding Engine (documented limitation).

Policy: only separable kinds; no capability to approve, push, create a PR, merge, commit,
install or write the parent checkout; at most ``MAX_PARALLEL`` units at once; never two units
holding overlapping files; parallel only when requests are independent.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

MAX_PARALLEL = 2
FORBIDDEN_CAPABILITIES = frozenset({"approve", "push", "create_pr", "merge", "write_parent", "install",
                                    "commit", "delete_branch"})


class DelegationKind(str, Enum):
    INVESTIGATE_TESTS = "investigate_tests"
    INSPECT_SUBSYSTEM = "inspect_subsystem"
    COMPARE_OPTIONS = "compare_options"
    READ_ONLY_RESEARCH = "read_only_research"
    PATCH_CANDIDATE = "patch_candidate"


READ_ONLY_KINDS = frozenset(DelegationKind) - {DelegationKind.PATCH_CANDIDATE}


class DelegationRefused(Exception):
    pass


@dataclass(frozen=True)
class DelegationRequest:
    kind: DelegationKind
    goal: str
    files: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()
    options: tuple[str, ...] = ()  # compare_options: the two alternatives, as queries


@dataclass
class DelegationPlan:
    requests: list[DelegationRequest]
    parallel: bool
    reasons: list[str] = field(default_factory=list)


def check_request(request: DelegationRequest) -> None:
    if not isinstance(request.kind, DelegationKind):
        raise DelegationRefused("unknown delegation kind")
    granted = set(request.capabilities) & FORBIDDEN_CAPABILITIES
    if granted:
        raise DelegationRefused(f"a delegated unit can never {', '.join(sorted(granted))}")
    if len(" ".join(request.goal.split())) < 20:
        raise DelegationRefused("a delegated goal must be specific and self-contained")
    if request.kind == DelegationKind.PATCH_CANDIDATE and not request.files:
        raise DelegationRefused("a patch candidate names the files it may change")
    if request.kind == DelegationKind.COMPARE_OPTIONS and len(request.options) != 2:
        raise DelegationRefused("compare_options needs exactly two options")


def plan_delegation(requests: Iterable[DelegationRequest]) -> DelegationPlan:
    """Parallel only when every request is valid and their file sets are disjoint."""
    items = list(requests)
    if not items:
        raise DelegationRefused("nothing to delegate")
    for request in items:
        check_request(request)
    if len(items) > MAX_PARALLEL:
        return DelegationPlan(items, False, [f"more than {MAX_PARALLEL} requests: run one at a time"])
    seen: set[str] = set()
    for request in items:
        overlap = seen & set(request.files)
        if overlap:
            return DelegationPlan(items, False, [f"overlapping files {sorted(overlap)}: run one at a time"])
        seen |= set(request.files)
    if len(items) == 1:
        return DelegationPlan(items, False, ["single request"])
    return DelegationPlan(items, True, ["independent requests on disjoint files"])


class FileLeases:
    """No two delegated units hold overlapping files; bounded concurrency."""

    def __init__(self, limit: int = MAX_PARALLEL) -> None:
        self.limit = limit
        self._held: dict[str, frozenset[str]] = {}
        self._lock = threading.Lock()

    def acquire(self, owner: str, files: Iterable[str]) -> None:
        wanted = frozenset(files)
        with self._lock:
            if len(self._held) >= self.limit:
                raise DelegationRefused(f"at most {self.limit} delegated units at once")
            for other, held in self._held.items():
                if held & wanted:
                    raise DelegationRefused(f"{sorted(held & wanted)} are already held by {other}")
            self._held[owner] = wanted

    def release(self, owner: str) -> None:
        with self._lock:
            self._held.pop(owner, None)

    @property
    def active(self) -> int:
        return len(self._held)


def _ranked(intel, query: str, limit: int = 8) -> list[dict[str, Any]]:
    return [{"path": r.path, "score": r.score, "why": list(r.reasons[:3])} for r in intel.rank(query, limit=limit)]


def investigate(intel, request: DelegationRequest) -> dict[str, Any]:
    """Read-only, in-process findings from the cached index; no writes are possible here."""
    check_request(request)
    if request.kind not in READ_ONLY_KINDS:
        raise DelegationRefused("patch candidates run as coding tasks")
    from meu_coding.relevance import is_test_path

    if request.kind == DelegationKind.COMPARE_OPTIONS:
        return {"kind": request.kind.value, "options": [{"option": o, "touches": _ranked(intel, o)}
                                                         for o in request.options]}
    focus = list(request.files) or [item["path"] for item in _ranked(intel, request.goal, 5)]
    findings = []
    for path in focus:
        reverse = intel.get_reverse_dependencies(path)
        findings.append({"path": path, "imports": list(intel.get_dependencies(path))[:15],
                         "imported_by": list(reverse)[:15],
                         "tests": sorted(p for p in reverse if is_test_path(p))[:10]})
    return {"kind": request.kind.value, "goal": request.goal, "ranked": _ranked(intel, request.goal),
            "findings": findings}


def run_investigations(intel, requests: list[DelegationRequest], leases: FileLeases | None = None) -> dict[str, Any]:
    plan = plan_delegation(requests)
    leases = leases or FileLeases()
    results = []
    for index, request in enumerate(plan.requests):
        owner = f"investigation-{index}"
        leases.acquire(owner, request.files)
        try:
            results.append(investigate(intel, request))
        finally:
            leases.release(owner)
    return {"parallel_allowed": plan.parallel, "reasons": plan.reasons, "results": results}


def start_patch_candidate(service, request: DelegationRequest, project_root: str,
                          leases: FileLeases | None = None) -> dict[str, Any]:
    """An independent patch candidate = a normal coding task on the named files (isolated
    worktree, Reviewer, explicit user approval). Never applied or approved here."""
    check_request(request)
    if request.kind != DelegationKind.PATCH_CANDIDATE:
        raise DelegationRefused("only patch candidates become coding tasks")
    if leases is not None:
        leases.acquire("patch-candidate", request.files)
    try:
        return service.start(request.goal, project_root, tuple(request.files))
    finally:
        if leases is not None:
            leases.release("patch-candidate")
