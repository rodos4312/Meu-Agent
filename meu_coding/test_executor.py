"""Controlled check execution inside an isolated workspace (Phase 2 ``CheckRunner``).

Each check becomes argv through :class:`CommandPolicy`; nothing else can run. Processes are
started by MEU's existing bounded runner (``hermes_cli._subprocess_compat.bounded_probe_run``:
argv only, no shell, Windows job object / POSIX process group, tree-kill on timeout) with
the child environment from ``tools.environments.local.hermes_subprocess_env`` (provider and
bot credentials removed), ``cwd`` set to the workspace, and bytecode/cache writes off.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from meu_coding.coding_interfaces import CheckKind, CheckResult, CheckSpec, CheckStatus
from meu_coding.command_policy import CommandBlocked, CommandPolicy
from meu_coding.validation_environment import pytest_python

DEFAULT_TIMEOUT = 600.0
MAX_OUTPUT = 8_000


@dataclass(frozen=True)
class RunOutcome:
    returncode: int | None  # None = timed out or could not start
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], str, Mapping[str, str], float], RunOutcome]


def meu_bounded_runner(argv: Sequence[str], cwd: str, env: Mapping[str, str], timeout: float) -> RunOutcome:
    from hermes_cli._subprocess_compat import bounded_probe_run

    completed = bounded_probe_run(list(argv), timeout=timeout, env=env, cwd=cwd)
    if completed is None:
        return RunOutcome(None, "", "timed out or could not start")
    return RunOutcome(completed.returncode, completed.stdout or "", completed.stderr or "")


def child_environment() -> dict[str, str]:
    from tools.environments.local import hermes_subprocess_env

    env = hermes_subprocess_env(inherit_credentials=False)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = ""
    return env


@dataclass(frozen=True)
class ExecutedCheck:
    check: CheckSpec
    argv: tuple[str, ...]
    result: CheckResult
    seconds: float


@dataclass
class TestExecutor:
    """Runs plan checks in ``workspace``; extra unit-test targets (tests the change added)
    fill checks that named none."""

    __test__ = False  # not a pytest test class

    workspace: Path
    policy: CommandPolicy = field(default_factory=CommandPolicy)
    runner: Runner = meu_bounded_runner
    env_factory: Callable[[], dict[str, str]] = child_environment
    python_resolver: Callable[[dict[str, str]], str] = pytest_python
    timeout: float = DEFAULT_TIMEOUT
    extra_test_targets: tuple[str, ...] = ()
    executed: list[ExecutedCheck] = field(default_factory=list)

    def _exists(self, rel: str) -> bool:
        root = self.workspace.resolve()
        target = (root / rel).resolve()
        return target.is_relative_to(root) and target.is_file()

    def _effective(self, check: CheckSpec) -> CheckSpec:
        if check.kind == CheckKind.UNIT_TEST and not check.targets and self.extra_test_targets:
            return CheckSpec(check.kind, check.description, self.extra_test_targets, check.command, check.required)
        return check

    def run(self, check: CheckSpec) -> CheckResult:
        effective = self._effective(check)
        try:
            planned = self.policy.plan(effective, self._exists)
        except CommandBlocked as exc:
            return self._record(check, (), CheckResult(check.key, CheckStatus.FAILED, f"blocked: {exc}"), 0.0)
        if planned is None:
            return self._record(check, (), CheckResult(check.key, CheckStatus.NOT_RUN, "nothing to run"), 0.0)
        started = time.perf_counter()
        environment = self.env_factory()
        if effective.kind == CheckKind.UNIT_TEST:
            try:
                policy = replace(self.policy, python=self.python_resolver(environment))
                planned = policy.plan(effective, self._exists)
            except (OSError, RuntimeError, ValueError, CommandBlocked) as exc:
                return self._record(check, (), CheckResult(check.key, CheckStatus.FAILED,
                                    f"pytest environment unavailable: {exc}"), time.perf_counter() - started)
        outcome = self.runner(planned.argv, str(self.workspace), environment, self.timeout)
        seconds = time.perf_counter() - started
        output = (outcome.stdout + outcome.stderr)[-MAX_OUTPUT:]
        if outcome.returncode is None:
            status = CheckStatus.FAILED
        else:
            status = CheckStatus.PASSED if outcome.returncode == 0 else CheckStatus.FAILED
        return self._record(check, planned.argv, CheckResult(check.key, status, output), seconds)

    def run_all(self, checks: Sequence[CheckSpec]) -> tuple[CheckResult, ...]:
        return tuple(self.run(check) for check in checks)

    def _record(self, check, argv, result, seconds) -> CheckResult:
        self.executed.append(ExecutedCheck(check, tuple(argv), result, round(seconds, 3)))
        return result
