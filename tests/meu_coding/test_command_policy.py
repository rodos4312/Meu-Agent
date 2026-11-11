import sys

import pytest

from meu_coding.coding_interfaces import CheckKind, CheckSpec, CheckStatus
from meu_coding.command_policy import CommandBlocked, CommandPolicy
from meu_coding.test_executor import RunOutcome, TestExecutor


def _policy(**kwargs):
    return CommandPolicy(detector=lambda command: (False, ""), ruff_locator=lambda: "/opt/bin/ruff", **kwargs)


def test_allowlisted_validation_commands():
    policy = _policy()
    exists = lambda path: True
    unit = policy.plan(CheckSpec(CheckKind.UNIT_TEST, "t", ("tests/test_ops.py",)), exists)
    assert unit.argv == (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_ops.py")
    syntax = policy.plan(CheckSpec(CheckKind.SYNTAX, "s", ("calc/ops.py",)), exists)
    assert syntax.argv == (sys.executable, "-m", "py_compile", "calc/ops.py")
    lint = policy.plan(CheckSpec(CheckKind.LINT, "l", ("calc/ops.py",)), exists)
    assert lint.argv == ("/opt/bin/ruff", "check", "--no-cache", "calc/ops.py")
    assert policy.plan(CheckSpec(CheckKind.UNIT_TEST, "t", ("calc/ops.py",)), exists) is None  # not a test file


@pytest.mark.parametrize("argv", [
    ("git", "reset", "--hard"), ("git", "push", "--force"), ("git", "clean", "-fdx"), ("git", "checkout", "main"),
    ("git", "switch", "x"), ("git", "merge", "x"), ("git", "rebase", "main"), ("rm", "-rf", "/"),
    ("cmd", "/c", "del", "/s", "x"), ("powershell", "Remove-Item", "-Recurse", "x"), ("format", "C:"),
    ("diskpart",), ("reg", "add", "HKLM\\x"), ("cmdkey", "/list"), ("pip", "install", "evil"),
    ("uv", "pip", "install", "x"), ("curl", "http://x"), ("/usr/bin/git.exe", "status"),
    (sys.executable, "-c", "import os; os.system('x')"), (sys.executable, "-m", "pip", "install", "x"),
    (sys.executable, "script.py"), ("ruff", "check", "--fix", "x.py"), ("python3", "-m", "pytest", "x"),
    (sys.executable, "-m", "pytest", "tests/x.py;rm -rf /"), (sys.executable, "-m", "pytest", "$(whoami)"),
])
def test_arbitrary_and_dangerous_commands_are_blocked(argv):
    with pytest.raises(CommandBlocked):
        _policy().validate(argv)


def test_meu_dangerous_command_detector_is_consulted():
    seen = []
    policy = CommandPolicy(detector=lambda c: (seen.append(c) or True, "flagged"), ruff_locator=lambda: None)
    with pytest.raises(CommandBlocked, match="flagged"):
        policy.validate((sys.executable, "-m", "pytest", "tests/test_x.py"))
    assert seen


def test_the_real_meu_detector_accepts_the_allowlist_and_flags_destruction():
    policy = CommandPolicy(ruff_locator=lambda: None)
    assert policy.validate((sys.executable, "-m", "pytest", "-q", "tests/test_ops.py"))
    detected, _ = policy.detector("git reset --hard HEAD")
    assert detected


def test_project_commands_need_trusted_registration():
    policy = _policy(project_commands={"build": ("make-safe-build",)})
    exists = lambda path: True
    assert policy.plan(CheckSpec(CheckKind.BUILD, "b", ("pyproject.toml",)), exists).argv == ("make-safe-build",)
    with pytest.raises(CommandBlocked, match="unregistered"):
        _policy().plan(CheckSpec(CheckKind.PROJECT_COMMAND, "p", (), command=("git", "push")), exists)
    with pytest.raises(CommandBlocked):
        _policy().plan(CheckSpec(CheckKind.UNIT_TEST, "t", ("../outside/test_x.py",)), exists)


def test_executor_runs_only_planned_argv_in_the_workspace(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    calls = []

    def runner(argv, cwd, env, timeout):
        calls.append((tuple(argv), cwd))
        return RunOutcome(1, "1 failed", "")

    executor = TestExecutor(tmp_path, policy=_policy(), runner=runner, env_factory=dict)
    result = executor.run(CheckSpec(CheckKind.UNIT_TEST, "t", ("tests/test_a.py", "tests/missing.py")))
    assert result.status == CheckStatus.FAILED and "1 failed" in result.output
    assert calls == [((sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_a.py"),
                      str(tmp_path))]
    blocked = executor.run(CheckSpec(CheckKind.PROJECT_COMMAND, "p", (), command=("git", "reset", "--hard")))
    assert blocked.status == CheckStatus.FAILED and blocked.output.startswith("blocked")
    assert len(calls) == 1  # nothing ran for the blocked command
    assert executor.run(CheckSpec(CheckKind.UNIT_TEST, "t", ())).status == CheckStatus.NOT_RUN
