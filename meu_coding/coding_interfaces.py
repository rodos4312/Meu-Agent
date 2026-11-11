"""Phase 2 data model: tasks, plans, proposals, reviews and the model-facing protocols.

Every value that crosses a stage boundary is a frozen dataclass, so a later stage cannot
alter what an earlier stage produced (the Reviewer sees exactly what the Coder proposed,
and the approval fingerprint covers exactly what was reviewed). The protocols at the end
are the only places a language model plugs in; nothing here imports a provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from meu_coding.interfaces import ContextBundle, RankedItem

# ── shared enums ────────────────────────────────────────────────────────────


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return _RISK_RANK[self]


_RISK_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


def max_risk(levels: Sequence[RiskLevel]) -> RiskLevel:
    return max(levels, key=lambda level: level.rank, default=RiskLevel.LOW)


class EditStrategy(str, Enum):
    """Output formats the Coder may use. The existing MEU patch/file tools execute them."""

    V4A_PATCH = "v4a_patch"
    SEARCH_REPLACE = "search_replace"
    WHOLE_FILE = "whole_file"
    UNIFIED_DIFF = "unified_diff"


class EditAction(str, Enum):
    UPDATE = "update"
    CREATE = "create"
    DELETE = "delete"


class ReviewStatus(str, Enum):
    PASS = "pass"
    FIX = "fix"
    BLOCK = "block"


# ── task and prepared context ───────────────────────────────────────────────


@dataclass(frozen=True)
class TaskConstraints:
    """``protected_paths`` are exact paths or directory prefixes ending in ``/``."""

    protected_paths: tuple[str, ...] = ()
    allow_new_files: bool = True
    allow_deletes: bool = False
    max_files: int = 12
    require_tests: bool = True


@dataclass(frozen=True)
class CodingTask:
    description: str
    constraints: TaskConstraints = TaskConstraints()
    explicit_files: tuple[str, ...] = ()
    recent_diff: str | None = None
    model_id: str = ""


@dataclass(frozen=True)
class TaskContext:
    """Prepared once per task by the orchestrator and shared by every stage."""

    task: CodingTask
    bundle: ContextBundle
    ranked: tuple[RankedItem, ...]
    dependencies: dict[str, tuple[str, ...]]
    reverse_dependencies: dict[str, tuple[str, ...]]
    known_paths: frozenset[str]
    file_bytes: dict[str, int] = field(default_factory=dict)

    def exists(self, path: str) -> bool:
        return path in self.known_paths


# ── test plan ───────────────────────────────────────────────────────────────


class CheckKind(str, Enum):
    SYNTAX = "syntax"
    LINT = "lint"
    UNIT_TEST = "unit_test"
    PROJECT_COMMAND = "project_command"
    BUILD = "build"


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class CheckSpec:
    """A check the plan requires. ``command`` is descriptive data for the safe execution
    layer; nothing in ``meu_coding`` runs it."""

    kind: CheckKind
    description: str
    targets: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    required: bool = True

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{','.join(self.targets)}"


@dataclass(frozen=True)
class CheckResult:
    key: str
    status: CheckStatus
    output: str = ""


@dataclass(frozen=True)
class TestPlan:
    __test__ = False  # not a pytest test class

    checks: tuple[CheckSpec, ...] = ()

    def of_kind(self, kind: CheckKind) -> tuple[CheckSpec, ...]:
        return tuple(c for c in self.checks if c.kind == kind)

    @property
    def test_files(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t for c in self.of_kind(CheckKind.UNIT_TEST) for t in c.targets))


# ── impact ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RiskReason:
    level: RiskLevel
    reason: str


@dataclass(frozen=True)
class ImpactReport:
    changed_files: tuple[str, ...]
    changed_symbols: tuple[str, ...]
    direct_dependencies: tuple[str, ...]
    reverse_dependencies: tuple[str, ...]
    affected_tests: tuple[str, ...]
    affected_config: tuple[str, ...]
    callers: tuple[str, ...]
    risk: RiskLevel
    reasons: tuple[RiskReason, ...]

    def explain(self) -> str:
        lines = [f"risk {self.risk.value}"]
        lines += [f"- [{r.level.value}] {r.reason}" for r in self.reasons]
        return "\n".join(lines)


# ── plan ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImplementationPlan:
    summary: str
    files_to_change: tuple[str, ...]
    symbols_to_change: tuple[str, ...]
    files_untouched: tuple[str, ...]
    steps: tuple[str, ...]
    test_plan: TestPlan
    risk: RiskLevel
    impact: ImpactReport | None = None
    new_files: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()

    @property
    def allowed_paths(self) -> frozenset[str]:
        return frozenset(self.files_to_change) | frozenset(self.new_files) | frozenset(self.test_plan.test_files)


@dataclass(frozen=True)
class PlanValidation:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


# ── proposal ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EditOperation:
    """One proposed edit. Exactly the payload fields of ``strategy`` are set:
    SEARCH_REPLACE → ``search``/``replace``; WHOLE_FILE → ``content``;
    V4A_PATCH / UNIFIED_DIFF → ``patch``."""

    path: str
    strategy: EditStrategy
    description: str
    action: EditAction = EditAction.UPDATE
    search: str | None = None
    replace: str | None = None
    content: str | None = None
    patch: str | None = None


@dataclass(frozen=True)
class StrategyChoice:
    strategy: EditStrategy
    profile: str
    reason: str


@dataclass(frozen=True)
class CodeChangeProposal:
    operations: tuple[EditOperation, ...]
    strategy: StrategyChoice
    assumptions: tuple[str, ...] = ()
    expected_tests: tuple[str, ...] = ()
    notes: str = ""
    format_errors: tuple[str, ...] = ()

    @property
    def affected_files(self) -> tuple[str, ...]:
        from meu_coding.edit_strategy import touched_paths

        return tuple(dict.fromkeys(p for op in self.operations for p in touched_paths(op)))

    @property
    def change_descriptions(self) -> tuple[str, ...]:
        return tuple(f"{op.path}: {op.description}" for op in self.operations)


# ── review ──────────────────────────────────────────────────────────────────


class FindingCategory(str, Enum):
    CORRECTNESS = "correctness"
    MISSING_REQUIREMENT = "missing_requirement"
    REGRESSION = "regression"
    RISKY_CHANGE = "risky_change"
    SCOPE_VIOLATION = "scope_violation"
    TEST_GAP = "test_gap"
    UNEXPECTED_FILE = "unexpected_file"


@dataclass(frozen=True)
class ReviewFinding:
    category: FindingCategory
    severity: ReviewStatus  # PASS = informational, FIX = must repair, BLOCK = stop
    message: str
    path: str | None = None
    repair: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    status: ReviewStatus
    findings: tuple[ReviewFinding, ...]
    repair_instructions: tuple[str, ...]
    confidence: float
    rationale: str

    def of(self, category: FindingCategory) -> tuple[ReviewFinding, ...]:
        return tuple(f for f in self.findings if f.category == category)

    @property
    def files_unexpectedly_touched(self) -> tuple[str, ...]:
        return tuple(f.path for f in self.of(FindingCategory.UNEXPECTED_FILE) if f.path)


# ── model-facing protocols (fakes in tests; real providers in Phase 3) ──────


@dataclass(frozen=True)
class PlanningRequest:
    task: CodingTask
    context: TaskContext
    draft: ImplementationPlan


@dataclass(frozen=True)
class RepairRequest:
    attempt: int
    previous: CodeChangeProposal
    review: ReviewResult


@dataclass(frozen=True)
class CodingRequest:
    task: CodingTask
    plan: ImplementationPlan
    context: TaskContext
    strategy: StrategyChoice
    max_context_chars: int
    repair: RepairRequest | None = None


@dataclass(frozen=True)
class CoderOutput:
    operations: tuple[EditOperation, ...]
    assumptions: tuple[str, ...] = ()
    expected_tests: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class ReviewRequest:
    task: CodingTask
    plan: ImplementationPlan
    proposal: CodeChangeProposal
    context: TaskContext
    diff: str | None = None
    test_results: tuple[CheckResult, ...] = ()


class PlanningModel(Protocol):
    def plan(self, request: PlanningRequest) -> ImplementationPlan: ...


class CodingModel(Protocol):
    def propose(self, request: CodingRequest) -> CoderOutput: ...


class ReviewModel(Protocol):
    def review(self, request: ReviewRequest) -> Sequence[ReviewFinding]: ...


@dataclass(frozen=True)
class StageRecord:
    stage: str
    detail: str = ""


@dataclass
class StageLog:
    records: list[StageRecord] = field(default_factory=list)

    def add(self, stage: str, detail: str = "") -> None:
        self.records.append(StageRecord(stage, detail))

    @property
    def stages(self) -> tuple[str, ...]:
        return tuple(r.stage for r in self.records)
