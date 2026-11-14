"""Real subprocess checks: pytest-less Python, PM fallback, truthful failures."""
import sys
import venv
from pathlib import Path
from types import SimpleNamespace

from meu_coding import validation_environment as validation
from meu_coding.coding_interfaces import CheckKind, CheckSpec, CheckStatus
from meu_coding.test_executor import TestExecutor, child_environment


def test_missing_pytest_uses_profile_pm_environment_and_runs_real_tests(tmp_path, monkeypatch):
    empty = tmp_path / "without-pytest"
    venv.EnvBuilder(with_pip=False).create(empty)
    from pm.environments import venv_python
    empty_python = venv_python(empty)
    monkeypatch.setattr(validation, "sys", SimpleNamespace(executable=str(empty_python)))
    monkeypatch.setattr("pm.environments.project_python", lambda root: empty_python)
    calls = []
    def provision(name, requirements, **kwargs):
        calls.append((name, requirements, kwargs))
        return Path(sys.executable)
    monkeypatch.setattr("pm.ensure_environment", provision)
    target = tmp_path / "test_value.py"
    target.write_text("def test_value():\n    assert 2 * 3 == 6\n")
    executor = TestExecutor(tmp_path)
    check = CheckSpec(CheckKind.UNIT_TEST, "real pytest", (target.name,))
    result = executor.run(check)
    assert result.status == CheckStatus.PASSED, result.output
    assert "1 passed" in result.output
    assert executor.executed[0].argv[0] == sys.executable
    from hermes_constants import get_hermes_home
    assert calls == [("coding-pytest", [validation.PYTEST_REQUIREMENT],
                      {"root": get_hermes_home() / "environments" / "coding-pytest", "timeout": 300})]
    assert not (empty / "Lib" / "site-packages" / "pytest").exists()
    target.write_text("def test_value():\n    assert 2 * 3 == 7\n")
    failed = executor.run(check)
    assert failed.status == CheckStatus.FAILED and "1 failed" in failed.output


def test_runtime_with_pytest_never_provisions(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected install")
    monkeypatch.setattr("pm.ensure_environment", forbidden)
    assert validation.pytest_python(child_environment()) == sys.executable


def test_missing_or_unsafe_targets_do_not_prepare_dependencies(tmp_path):
    def forbidden(env):
        raise AssertionError("dependency preparation before an executable check")
    executor = TestExecutor(tmp_path, python_resolver=forbidden)
    assert executor.run(CheckSpec(CheckKind.UNIT_TEST, "missing", ("test_missing.py",))).status == CheckStatus.NOT_RUN
    assert executor.run(CheckSpec(CheckKind.UNIT_TEST, "escape", ("../test_x.py",))).status == CheckStatus.FAILED


def test_pm_failure_is_reported_without_executing_tests(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_x(): pass\n")
    def unavailable(env):
        raise RuntimeError("offline: pytest environment missing")
    def forbidden(*args):
        raise AssertionError("test command must not run")
    executor = TestExecutor(tmp_path, python_resolver=unavailable, runner=forbidden)
    result = executor.run(CheckSpec(CheckKind.UNIT_TEST, "test", ("test_x.py",)))
    assert result.status == CheckStatus.FAILED
    assert "offline: pytest environment missing" in result.output
    assert executor.executed[0].argv == ()
