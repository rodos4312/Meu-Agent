"""Resume one accepted Windows update after a lost guardian or OS restart."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import psutil

if __package__:
    from hermes_cli import meu_recovery_runtime as runtime, meu_update_recovery as recovery
else:
    import meu_recovery_runtime as runtime
    import meu_update_recovery as recovery

TERMINAL = {"healthy", "cancelled", "rolled-back"}
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def logon_command(transaction: Path) -> str:
    python = transaction / "runtime" / "pythonw.exe"
    command = subprocess.list2cmdline([str(python), "-I", "-S", "-m", "meu_recovery_start"])
    if not python.is_file() or len(command) > 260:
        raise ValueError("Meu cannot register a bounded recovery command at this data location")
    return command


def register(transaction: Path) -> None:
    import winreg
    command = logon_command(transaction)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "MeuRecovery-" + transaction.name, 0, winreg.REG_SZ, command)


def unregister(transaction: Path) -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "MeuRecovery-" + transaction.name)
    except FileNotFoundError:
        pass  # Idempotent terminal cleanup; another guard may already have retired it.


def prepare(transaction: Path, parent, executable: Path, launcher: str, launcher_args: list[str]) -> None:
    if not (transaction / "payload.json").is_file():
        raise ValueError("Offline recovery runtime is missing; native handoff refused")
    recovery.write_record(transaction / "resume.json", {
        "schema": 1, "parentPid": parent.pid, "parentCreated": parent.create_time(),
        "executable": str(executable.resolve()), "launcher": launcher, "launcherArgs": launcher_args,
        "runtimeDirectory": os.environ.get("HERMES_RUNTIME_DIR"), "attempts": 0,
    })
    register(transaction)


def parent_alive(saved: dict) -> bool:
    try:
        parent = psutil.Process(saved["parentPid"])
        return (parent.is_running() and abs(parent.create_time() - saved["parentCreated"]) < 0.001
                and os.path.normcase(parent.exe()) == os.path.normcase(saved["executable"]))
    except psutil.NoSuchProcess:
        return False


def resume(transaction: Path, recover) -> str:
    record = recovery.read_record(transaction / "transaction.json")
    if record["state"] in TERMINAL:
        unregister(transaction)
        return record["state"]
    try:
        runtime.verify(transaction)
    except (OSError, ValueError):
        unregister(transaction)
        raise  # Corrupt retained code requires inspection, never another automatic logon loop.
    saved = recovery.read_record(transaction / "resume.json")
    # A completed target can have acknowledged health immediately before power loss.
    signal = transaction / "signal.json"
    receipt = recovery.read_record(signal) if signal.exists() else {}
    if (receipt.get("state") in {"healthy", "cancelled"} and receipt.get("commit") == record["target"]["commit"]
            and receipt.get("version") == record["target"]["version"]):
        recovery.write_record(transaction / "transaction.json", {**record, "state": receipt["state"]})
        unregister(transaction)
        return receipt["state"]
    if saved.get("schema") != 1:
        raise ValueError("Recovery identity is invalid")
    if parent_alive(saved):
        return "watching"  # A logon is not permission to interrupt the accepted update owner.
    if saved["attempts"] >= 3:
        unregister(transaction)
        raise ValueError("Automatic Meu recovery exhausted three logon attempts; retained backups need inspection")
    saved["attempts"] += 1
    recovery.write_record(transaction / "resume.json", saved)
    recover(transaction, Path(saved["executable"]), saved["launcher"], saved["parentCreated"], saved["launcherArgs"])
    unregister(transaction)
    return "rolled-back"


def finish(transaction: Path) -> None:
    if (transaction / "resume.json").is_file():
        record = recovery.read_record(transaction / "transaction.json")
        if record["state"] in TERMINAL:
            unregister(transaction)
