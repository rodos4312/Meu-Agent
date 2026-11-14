"""Resolve pytest without changing the running application environment.

Only trusted validation calls enter here, after execution approval. PM owns any
isolated dependency generation and honors the profile's lazy-install policy.
Project dependencies are not guessed or installed: missing ones remain test failures.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Same exact pytest version as the application's declared dev dependency.
PYTEST_REQUIREMENT = "pytest==9.1.1"


def pytest_python(environment: dict[str, str]) -> str:
    from hermes_cli._subprocess_compat import bounded_probe_run
    from hermes_constants import get_hermes_home
    from pm.environments import project_python

    home = get_hermes_home()
    candidates = [Path(sys.executable), project_python(Path(__file__).resolve().parents[1])]
    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file():
            continue
        probe = bounded_probe_run(
            [str(candidate), "-I", "-c", "import pytest"],
            cwd=str(home), env=environment, timeout=20,
        )
        if probe is not None and probe.returncode == 0:
            return str(candidate)
    from pm import ensure_environment

    return str(ensure_environment("coding-pytest", [PYTEST_REQUIREMENT],
                                  root=home / "environments" / "coding-pytest", timeout=300))
