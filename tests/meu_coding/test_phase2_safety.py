"""Phase 2 never mutates the repository, spawns processes, touches git or evaluates code.

The whole pipeline (context → plan → proposal → repairs → review → approval request) runs
with process spawning, eval/exec, file writes and filesystem mutation made to fail loudly,
against a repository whose code would leave marker files if anything imported or ran it.
Git mutation needs a process or a write, so it is covered by the same refusals.
"""

import builtins
import io
import os
import subprocess
from pathlib import Path

from meu_coding import CodingOrchestrator, CodingTask, OutcomeStatus
from meu_coding.coder import Coder
from tests.meu_coding.phase2_support import FIX_EDIT, REPO, TASK, ScriptedCoder, edit, good_output, make_intel, output


def _snapshot(root: Path):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_pipeline_never_writes_spawns_or_evaluates(make_repo, monkeypatch, tmp_path):
    hostile = dict(REPO, **{"app/__init__.py": "open('PWNED', 'w').write('x')\n"})
    intel = make_intel(make_repo, hostile)
    before = _snapshot(intel.root)

    def refuse(*args, **kwargs):
        raise AssertionError(f"Phase 2 tried a forbidden operation: {args!r}")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, refuse)
    monkeypatch.setattr(os, "system", refuse)
    monkeypatch.setattr(builtins, "eval", refuse)
    monkeypatch.setattr(builtins, "exec", refuse)
    real_open = builtins.open

    def read_only_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            refuse(file, mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", read_only_open)
    monkeypatch.setattr(io, "open", read_only_open)
    for name in ("remove", "unlink", "rename", "replace", "rmdir", "mkdir", "makedirs"):
        monkeypatch.setattr(os, name, refuse)
    monkeypatch.chdir(tmp_path)

    model = ScriptedCoder([output(FIX_EDIT, edit("web/routes.py", search="0.1", replace="0.2")), good_output()])
    result = CodingOrchestrator(intel, Coder(model)).run(CodingTask(TASK))

    assert result.status == OutcomeStatus.AWAITING_APPROVAL
    assert _snapshot(intel.root) == before
    assert not list(tmp_path.glob("PWNED*")) and not list(intel.root.rglob("PWNED*"))

