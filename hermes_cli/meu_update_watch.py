"""Watch a single accepted Meu update from the retained pre-update runtime.

No downloaded code runs here. Desktop stages this file and its recovery sibling
before handoff. The existing runtime bootstrap leases the OLD dependency set
for the lifetime of this process, so collection cannot delete the restore point.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import psutil

if __package__:
    from hermes_cli import meu_update_recovery as recovery
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import meu_update_recovery as recovery


def transition(transaction: Path, state: str, **fields) -> None:
    record = recovery.read_record(transaction / "transaction.json")
    recovery.write_record(transaction / "transaction.json", {**record, **fields, "state": state})


def signal_state(transaction: Path, commit: str, version: str) -> str | None:
    try:
        signal = recovery.read_record(transaction / "signal.json")
    except FileNotFoundError:
        return None
    if signal.get("commit") != commit or signal.get("version") != version:
        raise ValueError("Meu startup acknowledgement belongs to another build")
    return signal.get("state")


def stop_candidate(executable: Path, since: float) -> None:
    """Only this installed executable's new processes, never an argv substring."""
    expected = os.path.normcase(str(executable.resolve()))
    candidates = []
    for process in psutil.process_iter(["exe", "create_time"]):
        info = process.info
        if (info["exe"] and os.path.normcase(str(Path(info["exe"]).resolve())) == expected
                and info["create_time"] >= since):
            candidates.append(process)
    for process in candidates:
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            continue
    _gone, alive = psutil.wait_procs(candidates, timeout=15)
    for process in alive:
        process.kill()
    _gone, alive = psutil.wait_procs(alive, timeout=15)
    if alive:
        raise RuntimeError("Meu could not release its installed executable for recovery")


def run_cli(command: list[str], root: Path, home: Path, *, timeout: int = 120) -> str:
    result = subprocess.run(command, cwd=root, env={**os.environ, "HERMES_HOME": str(home)},
                            text=True, encoding="utf-8", errors="replace", capture_output=True,
                            timeout=timeout, check=True,
                            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    return result.stdout


def recover_installation(transaction: Path, executable: Path, launcher: str, since: float,
                         launcher_args: list[str] | None = None) -> None:
    record = recovery.read_record(transaction / "transaction.json")
    root, home = Path(record["root"]), Path(record["home"])
    transition(transaction, "recovering")
    command = [launcher, *(launcher_args or [])]
    try:
        run_cli([*command, "gateway", "stop"], root, home)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # A damaged import can prevent stop even when no owner exists. The
        # canonical maintenance reservation in restore still refuses a live one.
        pass
    record = recovery.restore(transaction, stop_desktop=lambda: stop_candidate(executable, since))
    # Prove the restored backend starts before replacing the desktop package.
    endpoint = json.loads(run_cli([*command, "gateway", "ensure", "--json"], root, home, timeout=300))
    if (not isinstance(endpoint, dict) or endpoint.get("state") != "ready"
            or endpoint.get("client_code_sha") != record["sourceCommit"]
            or endpoint.get("endpoint", {}).get("code_sha") != record["sourceCommit"]):
        raise RuntimeError("Restored Meu gateway did not report a usable endpoint")
    run_cli([*command, "gateway", "stop"], root, home)
    installer = recovery.verify_release(record["rollback"], record["key"], Path(record["directory"]))
    if os.name != "nt":
        raise RuntimeError("Meu desktop package rollback is supported on Windows only")
    result = subprocess.run([str(installer), "--updated", "/S", "--force-run", f"/D={executable.parent}"],
                            timeout=300, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f"Previous Meu installer failed ({result.returncode})")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    version = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command",
                              "(Get-Item -LiteralPath $env:MEU_RECOVERY_EXE).VersionInfo.FileVersion"],
                             env={**os.environ, "MEU_RECOVERY_EXE": str(executable)}, check=True,
                             capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if version.stdout.strip() != record["rollback"]["version"]:
        raise RuntimeError("Previous Meu desktop version was not installed")
    transition(transaction, "rolled-back", restoredCommit=record["sourceCommit"])


def watch(transaction: Path, parent_pid: int, executable: Path, launcher: str,
          *, launcher_args: list[str] | None = None, timeout: float = 1200,
          wait=threading.Event().wait, clock=time.monotonic) -> str:
    """One bounded handoff; cancellation never restores over a running old app."""
    record = recovery.read_record(transaction / "transaction.json")
    recovery.verify_release(record["rollback"], record["key"], Path(record["directory"]))
    parent = psutil.Process(parent_pid)
    since = parent.create_time()
    if os.path.normcase(parent.exe()) != os.path.normcase(str(executable.resolve())):
        raise ValueError("Recovery parent does not own this Meu executable")
    transition(transaction, "watching", watcherPid=os.getpid())
    deadline = clock() + timeout
    # Polling also observes cancellation while the old process remains alive.
    while parent.is_running():
        if signal_state(transaction, record["target"]["commit"], record["target"]["version"]) == "cancelled" or clock() >= deadline:
            transition(transaction, "cancelled")
            return "cancelled"
        wait(0.25)
    while clock() < deadline:
        signal = signal_state(transaction, record["target"]["commit"], record["target"]["version"])
        if signal in ("healthy", "cancelled"):
            transition(transaction, signal)
            return signal
        if signal == "failed":
            break
        wait(0.25)
    recover_installation(transaction, executable, launcher, since, launcher_args)
    return "rolled-back"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transaction", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--launcher", required=True)
    parser.add_argument("--launcher-args", type=json.loads, default=[])
    args = parser.parse_args()
    try:
        if not isinstance(args.launcher_args, list) or any(not isinstance(value, str) or "\0" in value for value in args.launcher_args):
            raise ValueError("Invalid Meu recovery launcher arguments")
        watch(args.transaction, args.parent_pid, args.executable, args.launcher, launcher_args=args.launcher_args)
    except Exception as exc:
        transition(args.transaction, "recovery-failed", error=str(exc))
        logging.exception("Meu update recovery failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
