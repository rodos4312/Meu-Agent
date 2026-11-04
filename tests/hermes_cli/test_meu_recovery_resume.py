"""Cold-process recovery, bounded ownership and native Windows file/logon contracts."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import psutil
import pytest

from hermes_cli import meu_recovery_resume as resume, meu_recovery_runtime as runtime
from hermes_cli import meu_recovery_windows as windows, meu_update_recovery as recovery
from hermes_cli import meu_update_watch as watcher
from tests.hermes_cli.test_meu_update_recovery import sql
from tests.waiting import wait_until

pytest_plugins = ["tests.hermes_cli.test_meu_update_recovery"]


@pytest.fixture
def pending(tmp_path, monkeypatch):
    transaction = tmp_path / "pending"
    transaction.mkdir()
    current = psutil.Process()
    target = {"commit": "a" * 40, "version": "0.1.0-dev.17"}
    recovery.write_record(transaction / "transaction.json", {"state": "watching", "target": target})
    recovery.write_record(transaction / "resume.json", {
        "schema": 1, "parentPid": current.pid, "parentCreated": current.create_time() - 1,
        "executable": current.exe(), "launcher": sys.executable, "launcherArgs": ["-I", "owned.py"], "attempts": 0,
    })
    monkeypatch.setattr(runtime, "verify", lambda _path: None)
    removed = []
    monkeypatch.setattr(resume, "unregister", lambda path: removed.append(path))
    return transaction, target, removed


@pytest.mark.parametrize("state", ["healthy", "cancelled"])
def test_completed_receipt_survives_guardian_loss_without_replaying_recovery(pending, state):
    transaction, target, removed = pending
    recovery.write_record(transaction / "signal.json", {**target, "state": state})
    assert resume.resume(transaction, lambda *_args: pytest.fail("Recovery must not replay")) == state
    assert recovery.read_record(transaction / "transaction.json")["state"] == state
    assert removed == [transaction]


def test_cold_resume_keeps_the_original_command_prefix_and_rejects_wrong_version_receipt(pending):
    transaction, target, removed = pending
    recovery.write_record(transaction / "signal.json", {**target, "state": "healthy", "version": "0.1.0-dev.16"})
    calls = []
    assert resume.resume(transaction, lambda *args: calls.append(args)) == "rolled-back"
    assert calls[0][2:] == (sys.executable, psutil.Process().create_time() - 1, ["-I", "owned.py"])
    assert recovery.read_record(transaction / "resume.json")["attempts"] == 1
    assert removed == [transaction]


def test_resume_does_not_confuse_a_recycled_pid_with_the_original_owner(pending):
    transaction, _target, _removed = pending
    saved = recovery.read_record(transaction / "resume.json")
    assert not resume.parent_alive(saved)
    saved["parentCreated"] = psutil.Process().create_time()
    assert resume.parent_alive(saved)
    recovery.write_record(transaction / "resume.json", saved)
    assert resume.resume(transaction, lambda *_args: pytest.fail("Live owner must be preserved")) == "watching"
    assert recovery.read_record(transaction / "resume.json")["attempts"] == 0


def test_failed_resume_is_bounded_and_retains_its_transaction(pending):
    transaction, _target, removed = pending
    def fail(*_args):
        raise OSError("File is locked")
    for _ in range(3):
        with pytest.raises(OSError, match="locked"):
            resume.resume(transaction, fail)
    with pytest.raises(ValueError, match="three logon attempts"):
        resume.resume(transaction, fail)
    assert (transaction / "transaction.json").is_file()
    assert removed == [transaction]


def test_corrupt_retained_payload_retires_logon_without_executing_recovery(pending, monkeypatch):
    transaction, _target, removed = pending
    def corrupt(_path):
        raise ValueError("Retained payload changed")
    monkeypatch.setattr(runtime, "verify", corrupt)
    with pytest.raises(ValueError, match="payload changed"):
        resume.resume(transaction, lambda *_args: pytest.fail("Corrupt payload must not execute"))
    assert removed == [transaction]
    assert recovery.read_record(transaction / "resume.json")["attempts"] == 0


def test_restore_can_continue_after_a_real_process_dies_after_database_import(installation):
    home, root, cache, key, old, new, git, facts, homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    git("merge", "--ff-only", new)
    for profile in homes:
        sql(profile / "state.db", "ALTER TABLE payload ADD COLUMN incompatible TEXT")
        sql(profile / "state.db", "UPDATE payload SET value='failed version'")
    facts.write_text('{"new":true}', encoding="utf-8")
    script = (
        "import os,sys;from pathlib import Path;"
        f"sys.path.insert(0,{str(Path(recovery.__file__).parents[1])!r});"
        "from hermes_cli import meu_update_recovery as r;"
        f"r.runtime_facts_path=lambda root:Path({str(facts)!r});"
        "original=r.backup.run_import;"
        "r.backup.run_import=lambda args:(original(args),os._exit(79))[0];"
        f"r.restore(Path({str(transaction)!r}))"
    )
    result = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, timeout=60, check=False)
    assert result.returncode == 79, result.stderr.decode(errors="replace")
    restored = recovery.restore(transaction)
    assert restored["state"] == "restored"
    assert git("rev-parse", "HEAD") == old
    assert json.loads(facts.read_text()) == {"old": True}
    for profile in homes:
        assert sql(profile / "state.db", "SELECT * FROM payload") == [("old",)]
    assert (transaction / "failed-state.zip").is_file()


def test_missing_runtime_repair_failure_stops_before_rewinding_code_or_profile(installation):
    home, root, cache, key, _old, new, git, _facts, homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    git("merge", "--ff-only", new)
    for profile in homes:
        sql(profile / "state.db", "ALTER TABLE payload ADD COLUMN failed_version TEXT")

    def refuse():
        raise ValueError("Existing runtime bytes differ")

    with pytest.raises(ValueError, match="runtime bytes differ"):
        recovery.restore(transaction, restore_runtime=refuse)
    assert git("rev-parse", "HEAD") == new
    for profile in homes:
        assert "failed_version" in [row[1] for row in sql(profile / "state.db", "PRAGMA table_info(payload)")]


def test_collected_environment_is_recreated_without_overwriting_foreign_bytes(tmp_path, monkeypatch):
    from hermes_cli.runtime_state import collect_generations
    from pm.environments import install_state_dir, runtime_facts_path
    home, root, transaction = (tmp_path / name for name in ("home", "checkout", "retained"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEU_HOME", str(home))
    current = install_state_dir(root) / "environments/current/venv"
    old = install_state_dir(root) / "environments/old/venv"
    for environment in (old, current):
        environment.mkdir(parents=True)
        (environment / "pyvenv.cfg").write_text("captured environment", encoding="utf-8")
    (old.parent / ".lease-managed").touch()
    recovery.write_record(runtime_facts_path(root), {"packages": {"venv": {"environment": str(current)}}})
    captured = transaction / "environment/pyvenv.cfg"
    captured.parent.mkdir(parents=True)
    os.link(old / "pyvenv.cfg", captured)
    recovery.write_record(transaction / "payload.json", {
        "schema": 1, "files": {"environment/pyvenv.cfg": recovery.digest(captured)},
        "locations": {"environment": str(old)}, "managedEnvironment": True,
    })
    recovery.write_record(transaction / "transaction.json", {"payloadHash": recovery.digest(transaction / "payload.json")})
    assert old.parent in collect_generations(root, min_age_seconds=0)
    assert not old.exists()
    runtime.rehydrate(transaction)
    assert (old / "pyvenv.cfg").read_text(encoding="utf-8") == "captured environment"
    assert (old.parent / ".lease-managed").is_file()
    # Replace the restored hard link before editing, preserving retained immutable bytes.
    (old / "pyvenv.cfg").unlink()
    (old / "pyvenv.cfg").write_text("foreign edit", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from the retained generation"):
        runtime.rehydrate(transaction)
    assert (old / "pyvenv.cfg").read_text(encoding="utf-8") == "foreign edit"
    payload = recovery.read_record(transaction / "payload.json")
    elsewhere = tmp_path / "foreign-destination"
    payload["locations"]["environment"] = str(elsewhere)
    recovery.write_record(transaction / "payload.json", payload)
    with pytest.raises(ValueError, match="manifest changed"):
        runtime.rehydrate(transaction)
    assert not elsewhere.exists()


@pytest.mark.platforms("windows")
def test_cross_volume_restore_never_publishes_partial_files_or_overwrites_foreign_bytes(tmp_path, monkeypatch):
    source, destination = tmp_path / "captured.dll", tmp_path / "restored.dll"
    source.write_bytes(b"captured immutable library")
    copy = shutil.copyfileobj

    def different_volume(*_args):
        raise OSError("Controlled cross-volume hard-link refusal")

    def interrupted(_source, output):
        output.write(b"partial")
        raise OSError("Controlled interrupted copy")

    monkeypatch.setattr(runtime.os, "link", different_volume)
    monkeypatch.setattr(runtime.shutil, "copyfileobj", interrupted)
    with pytest.raises(OSError, match="interrupted copy"):
        runtime._restore_file(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".meu-restore-*"))
    monkeypatch.setattr(runtime.shutil, "copyfileobj", copy)
    runtime._restore_file(source, destination)
    assert destination.read_bytes() == source.read_bytes()
    destination.write_bytes(b"foreign edit")
    with pytest.raises(FileExistsError):
        runtime._restore_file(source, destination)
    assert destination.read_bytes() == b"foreign edit"
    assert not list(tmp_path.glob(".meu-restore-*"))


def test_native_installer_identity_must_match_the_signed_target_bytes(installation):
    home, root, cache, key, _old, _new, _git, _facts, _homes = installation
    journal = recovery.read_record(cache / "meu-update-recovery.json")
    native = cache / journal["target"]["file"]
    journal["nativeInstaller"] = str(native.resolve())
    recovery.write_record(cache / "meu-update-recovery.json", journal)
    transaction = recovery.prepare(root, home, cache, key, "git")
    assert recovery.read_record(transaction / "transaction.json")["nativeInstaller"] == str(native.resolve())
    native.write_bytes(b"changed native executable")
    with pytest.raises(ValueError, match="signed release"):
        recovery.prepare(root, home, cache, key, "git")


@pytest.mark.platforms("windows")
def test_recovery_waits_for_the_real_native_owner_instead_of_killing_it(tmp_path):
    executable = tmp_path / "owned-installer.exe"
    shutil.copy2(Path(os.environ["SystemRoot"]) / "System32/cmd.exe", executable)
    child = subprocess.Popen([str(executable), "/d", "/q", "/c", 'set /p "meuFixture="'], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    recovery.write_record(tmp_path / "transaction.json", {"state": "watching", "nativeInstaller": str(executable)})
    observed = threading.Event()
    def release():
        if wait_until(lambda: recovery.read_record(tmp_path / "transaction.json")["state"] == "waiting-for-installer", timeout=5):
            observed.set()
        child.stdin.close()
    reader = threading.Thread(target=release)
    try:
        since = psutil.Process(child.pid).create_time()
        reader.start()
        watcher.wait_for_native_installer(tmp_path, since, timeout=10)
        reader.join(timeout=6)
        assert observed.is_set()
        assert child.wait(timeout=5) in (0, 1)
    finally:
        if not child.stdin.closed:
            child.stdin.close()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


@pytest.mark.platforms("windows")
def test_windows_file_holder_is_preserved_and_recovery_proceeds_after_release(tmp_path):
    file = tmp_path / "app.asar"
    file.write_bytes(b"owned package fixture")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(file), 0x80000000, 1, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        assert windows.blocked_file(tmp_path) == file
        with pytest.raises(TimeoutError, match="still locked"):
            windows.wait_for_package(tmp_path, timeout=0)
        assert file.read_bytes() == b"owned package fixture"
    finally:
        kernel.CloseHandle(handle)
    windows.wait_for_package(tmp_path, timeout=0)


@pytest.mark.platforms("windows")
def test_windows_registration_is_private_to_this_transaction_and_terminal_cleanup_is_idempotent(tmp_path, monkeypatch):
    import winreg
    transaction = tmp_path / "meu-update-fixture"
    (transaction / "runtime").mkdir(parents=True)
    (transaction / "runtime" / "pythonw.exe").write_bytes(b"not executable")
    monkeypatch.setattr(resume, "RUN_KEY", "Software\\MeuAgent\\Tests\\" + tmp_path.name)
    name = "MeuRecovery-" + transaction.name
    try:
        resume.register(transaction)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, resume.RUN_KEY) as key:
            command, kind = winreg.QueryValueEx(key, name)
        assert kind == winreg.REG_SZ
        assert command == resume.logon_command(transaction)
        assert " -I -S -m meu_recovery_start" in command
    finally:
        resume.unregister(transaction)
        resume.unregister(transaction)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, resume.RUN_KEY) as key:
        with pytest.raises(FileNotFoundError):
            winreg.QueryValueEx(key, name)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, resume.RUN_KEY)


@pytest.mark.platforms("windows")
def test_retained_interpreter_runs_offline_without_editable_paths_and_detects_damaged_helpers(tmp_path, monkeypatch):
    root = Path(recovery.__file__).parents[1]
    commit = recovery.git(root, "git", "rev-parse", "HEAD")
    transaction = tmp_path / "retained"
    transaction.mkdir()
    recovery.write_record(transaction / "transaction.json", {
        "state": "prepared", "root": str(root), "git": "git", "sourceCommit": commit,
    })
    monkeypatch.setattr(runtime, "selected_venv", lambda _root: Path(sys.prefix))
    runtime.freeze(transaction)
    runtime.verify(transaction)
    script = (
        "import sys,json;from pathlib import Path;"
        f"p=Path({str(transaction)!r});"
        "sys.path[:0]=[str(p),str(p/'source'),str(p/'environment/Lib/site-packages')];"
        "import psutil,cryptography,meu_update_recovery;"
        "print(json.dumps([sys.base_prefix,psutil.__file__,cryptography.__file__]))"
    )
    result = subprocess.run([str(transaction / "runtime" / "python.exe"), "-I", "-S", "-c", script],
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert all(Path(name).resolve().is_relative_to(transaction.resolve()) for name in json.loads(result.stdout))
    recovery.write_record(transaction / "transaction.json", {
        **recovery.read_record(transaction / "transaction.json"), "state": "healthy", "home": str(tmp_path),
    })
    recovery.write_record(transaction / "resume.json", {"runtimeDirectory": None})
    startup = subprocess.run([str(transaction / "runtime" / "pythonw.exe"), "-I", "-S", "-m", "meu_recovery_start"],
                             capture_output=True, timeout=60, check=False)
    assert startup.returncode == 0, (transaction / "watch.log").read_text(encoding="utf-8")
    payload = recovery.read_record(transaction / "payload.json")
    payload["locations"] = {name: str(tmp_path / "recreated" / name) for name in ("runtime", "environment")}
    payload["managedEnvironment"] = False
    recovery.write_record(transaction / "payload.json", payload)
    recovery.write_record(transaction / "transaction.json", {
        **recovery.read_record(transaction / "transaction.json"), "payloadHash": recovery.digest(transaction / "payload.json"),
    })
    runtime.rehydrate(transaction)
    probe = subprocess.run([str(tmp_path / "recreated/runtime/python.exe"), "-I", "-S", "-c",
                            "import sys;sys.path.insert(0,sys.argv[1]);import psutil,cryptography",
                            str(tmp_path / "recreated/environment/Lib/site-packages")],
                           capture_output=True, timeout=60, check=False)
    assert probe.returncode == 0, probe.stderr
    # This helper is a separate copy; never mutate the hard-linked PM generations.
    (transaction / "meu_update_watch.py").write_text("damaged helper", encoding="utf-8")
    with pytest.raises(ValueError, match="payload changed"):
        runtime.verify(transaction)
