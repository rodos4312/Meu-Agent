"""Phase 3 fixtures: a real temporary git repository and deterministic fake models."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from meu_coding import CodingTask, analyze_repository
from meu_coding.coder import Coder
from meu_coding.coding_interfaces import CoderOutput, CodingRequest, EditOperation
from meu_coding.coding_session import CodingSession
from meu_coding.safe_execution import ExecutionDecision, SafeExecutionAdapter
from meu_coding.test_executor import RunOutcome, TestExecutor

SAMPLE = {
    "calc/__init__.py": "",
    "calc/ops.py": "def sub(a, b):\n    return a - b\n",
    "tests/__init__.py": "",
    "tests/test_ops.py": "from calc.ops import sub\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n",
    ".gitignore": ".worktrees/\n__pycache__/\n",
    "AGENTS.md": "# rules\n",
}
TASK = CodingTask("Add a small function `add` in calc/ops.py and a unit test",
                  explicit_files=("calc/ops.py", "tests/test_ops.py"))

ADD_FN = ("def sub(a, b):\n", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n")
BAD_ADD_FN = ("def sub(a, b):\n", "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n")
ADD_TEST = ("def test_sub():\n",
            "def test_add():\n    from calc.ops import add\n    assert add(2, 3) == 5\n\n\ndef test_sub():\n")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def commit_all(repo: Path, message: str = "change") -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", message)


def make_git_repo(root: Path) -> Path:
    repo = root / "repo"
    for rel, content in SAMPLE.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "core.autocrlf", "false")
    commit_all(repo, "initial")
    return repo


def snapshot(repo: Path) -> dict[str, bytes]:
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in sorted(repo.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(repo).parts[:1] and ".worktrees" not in p.parts}


def edits(request: CodingRequest, *pairs: tuple[str, tuple[str, str]]) -> CoderOutput:
    return CoderOutput(tuple(EditOperation(path, request.strategy.strategy, f"edit {path}", search=s, replace=r)
                             for path, (s, r) in pairs))


@dataclass
class ScriptedModel:
    """Each call returns the next scripted builder's output."""

    builders: list
    requests: list = field(default_factory=list)

    def propose(self, request: CodingRequest) -> CoderOutput:
        self.requests.append(request)
        return self.builders[min(len(self.requests), len(self.builders)) - 1](request)


def good(request):
    return edits(request, ("calc/ops.py", ADD_FN), ("tests/test_ops.py", ADD_TEST))


def buggy(request):
    return edits(request, ("calc/ops.py", BAD_ADD_FN), ("tests/test_ops.py", ADD_TEST))


def fake_runner(returncode=0, output="ok"):
    calls = []

    def run(argv, cwd, env, timeout):
        calls.append((tuple(argv), cwd))
        return RunOutcome(returncode, output, "")
    run.calls = calls
    return run


def fake_adapter(runner=None) -> SafeExecutionAdapter:
    runner = runner or fake_runner()
    return SafeExecutionAdapter(executor_factory=lambda root, extra: TestExecutor(
        root, runner=runner, env_factory=dict, extra_test_targets=extra))


def session_for(repo: Path, builders, adapter=None, **kwargs) -> CodingSession:
    return CodingSession(analyze_repository(repo), Coder(ScriptedModel(builders)),
                         adapter=adapter or fake_adapter(), **kwargs)


def yes(request) -> ExecutionDecision:
    return ExecutionDecision(True, "tester", request.approval_id, request.fingerprint)
