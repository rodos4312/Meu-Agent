"""Test plans and check interfaces.

The Architect states which checks a change needs (:func:`build_test_plan`); the Reviewer
reads their results. Running a check is the safe execution layer's job: ``CheckRunner``
is the seam Phase 3 implements on top of MEU's approved terminal tooling. The only check
implemented here, :func:`static_syntax_errors`, parses proposed Python text in memory with
``ast.parse`` (parsing never executes code).
"""

from __future__ import annotations

import ast
import posixpath
from collections.abc import Iterable
from typing import Protocol

from meu_coding.coding_interfaces import (
    CheckKind,
    CheckResult,
    CheckSpec,
    CodeChangeProposal,
    EditAction,
    EditStrategy,
    TestPlan,
)
from meu_coding.relevance import is_test_path
from meu_coding.scope import is_config_path

_LINTABLE = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
             ".tsx": "typescript", ".mjs": "javascript", ".cjs": "javascript"}


class CheckRunner(Protocol):
    """Runs one check through the safe execution layer (approvals, sandbox, worktree)."""

    def run(self, check: CheckSpec) -> CheckResult: ...


def build_test_plan(changed_files: Iterable[str], affected_tests: Iterable[str]) -> TestPlan:
    files = tuple(dict.fromkeys(changed_files))
    tests = tuple(dict.fromkeys(affected_tests))
    code = tuple(f for f in files if posixpath.splitext(f)[1] in _LINTABLE)
    checks: list[CheckSpec] = []
    if code:
        checks.append(CheckSpec(CheckKind.SYNTAX, "changed source files parse", code))
        checks.append(CheckSpec(CheckKind.LINT, "project lint on changed files", code))
    if tests:
        checks.append(CheckSpec(CheckKind.UNIT_TEST, "tests covering the changed code", tests))
    elif any(not is_test_path(f) for f in code):
        checks.append(CheckSpec(CheckKind.UNIT_TEST, "add or name a test for the changed behaviour",
                                (), required=True))
    if any(is_config_path(f) for f in files):
        checks.append(CheckSpec(CheckKind.BUILD, "project builds with the changed configuration",
                                tuple(f for f in files if is_config_path(f))))
    return TestPlan(tuple(checks))


def static_syntax_errors(proposal: CodeChangeProposal) -> list[tuple[str, str]]:
    """``(path, message)`` for whole-file Python content that does not parse."""
    errors = []
    for op in proposal.operations:
        if (op.strategy == EditStrategy.WHOLE_FILE and op.action != EditAction.DELETE
                and op.path.endswith(".py") and op.content is not None):
            try:
                ast.parse(op.content, filename=op.path)
            except SyntaxError as exc:
                errors.append((op.path, f"line {exc.lineno}: {exc.msg}"))
    return errors
