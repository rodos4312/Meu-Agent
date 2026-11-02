"""Read-only, credential-safe latency probe for Hermes Computer Use on Windows.

No mouse/keyboard events or installations are performed. Command output is
deliberately not saved: doctor output may contain local paths or identifiers.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime


CHECKS = (
    ("status", "computer-use", "status"),
    ("doctor", "computer-use", "doctor"),
    ("permissions", "computer-use", "permissions", "status"),
)


def probe(command: tuple[str, ...], *, timeout: float = 35.0) -> dict:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            ["hermes", *command[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        status = "ok" if completed.returncode == 0 else "nonzero"
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        status, returncode = "timeout", None
    except OSError:
        status, returncode = "spawn_error", None
    return {
        "check": command[0],
        "status": status,
        "returncode": returncode,
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=3, choices=range(1, 11), metavar="1..10")
    parser.add_argument("--timeout", type=float, default=35.0)
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 10 or not 1 <= args.timeout <= 120:
        parser.error("rounds must be 1..10; timeout must be 1..120 seconds")

    result = {
        "schema_version": 1,
        "generated_utc": datetime.now(UTC).isoformat(),
        "os": platform.system(),
        "python": platform.python_version(),
        "hermes_found": shutil.which("hermes") is not None,
        "scope": "read_only_cli_diagnostics_not_gui_benchmark",
        "measurements": [],
    }
    if not result["hermes_found"]:
        print(json.dumps(result, indent=2))
        return 2

    for _ in range(args.rounds):
        for command in CHECKS:
            result["measurements"].append(probe(command, timeout=args.timeout))
    print(json.dumps(result, indent=2))
    return 0 if all(m["status"] == "ok" for m in result["measurements"]) else 1


if __name__ == "__main__":
    sys.exit(main())
