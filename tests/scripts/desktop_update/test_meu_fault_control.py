"""Private CI faults target only the owned Windows process, despite timestamp rounding."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import psutil
import pytest


@pytest.fixture
def control():
    source = Path(__file__).resolve().parents[3] / "apps/desktop/scripts/meu-recovery-control.py"
    spec = importlib.util.spec_from_file_location("meu_fault_control", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.platforms("windows")
def test_native_fault_refuses_foreign_identity_and_accepts_submillisecond_rounding(control, tmp_path):
    executable = tmp_path / "owned-cmd.exe"
    shutil.copy2(Path(os.environ["SystemRoot"]) / "System32/cmd.exe", executable)
    with subprocess.Popen([str(executable), "/D", "/Q"], stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=subprocess.CREATE_NO_WINDOW) as child:
        try:
            created = psutil.Process(child.pid).create_time()
            with pytest.raises(ValueError, match="expected executable"):
                control.end_owned(child.pid, str(tmp_path / "foreign.exe"), created, created)
            with pytest.raises(ValueError, match="creation time"):
                control.end_owned(child.pid, str(executable), created, created + 10)
            assert child.poll() is None
            # Both native interfaces identify this exact owned process within 1 ms.
            control.end_owned(child.pid, str(executable), created + 0.0005, created + 0.0005)
            assert child.wait(timeout=10) == 83
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)


@pytest.mark.platforms("windows")
def test_fault_cli_refuses_to_run_outside_disposable_github_environment(control):
    env = {key: value for key, value in os.environ.items() if key not in {"GITHUB_ACTIONS", "GITHUB_REPOSITORY"}}
    result = subprocess.run([sys.executable, "-I", control.__file__], env=env, capture_output=True,
                            text=True, timeout=30, check=False)
    assert result.returncode != 0
    assert "requires the disposable Meu Windows runner" in result.stderr
