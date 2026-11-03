"""Offline recovery uses real Git, signed fixtures, SQLite and canonical reservations."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import pytest
import psutil
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.exceptions import InvalidSignature

from gateway.runtime_ownership import OwnershipConflict, ProfileOwnership
from hermes_cli import meu_update_recovery as recovery
from hermes_cli import meu_update_watch as watcher


def sql(path, statement):
    with sqlite3.connect(path) as db:
        return db.execute(statement).fetchall()


@pytest.fixture
def installation(tmp_path_factory, monkeypatch):
    tmp_path = tmp_path_factory.mktemp("meu")
    home, root, cache = (tmp_path / name for name in ("home", "checkout", "cache"))
    for directory in (home, root, cache):
        directory.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEU_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    facts = home / "installs" / "test" / "facts.json"
    facts.parent.mkdir(parents=True)
    facts.write_text('{"old":true}', encoding="utf-8")
    monkeypatch.setattr(recovery, "runtime_facts_path", lambda _root: facts)
    git = lambda *args: recovery.git(root, "git", *args)
    git("init", "-b", recovery.BRANCH)
    git("config", "user.name", "Recovery fixture")
    git("config", "user.email", "test@example.invalid")
    git("remote", "add", "origin", recovery.REPOSITORY)
    (root / "backend.py").write_text("old = True\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "old")
    old = git("rev-parse", "HEAD")
    (root / "backend.py").write_text("new = True\n", encoding="utf-8")
    git("commit", "-am", "new")
    new = git("rev-parse", "HEAD")
    git("reset", "--keep", old)
    private = Ed25519PrivateKey.generate()
    key = base64.b64encode(private.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).decode()

    def release(version, commit):
        filename = f"Meu-{version}-win-x64.exe"
        raw = b"not executable; recovery test fixture"
        (cache / filename).write_bytes(raw)
        value = dict(schema=2, repository="rodos4312/Meu-Agent", branch=recovery.BRANCH,
                     channel="meu-preview", publisherName="", version=version, commit=commit,
                     file=filename, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                     sha512=base64.b64encode(hashlib.sha512(raw).digest()).decode())
        payload = ["Meu Windows update v2", *(value[field] for field in recovery.FIELDS)]
        value["signature"] = base64.b64encode(private.sign(json.dumps(payload, separators=(",", ":")).encode())).decode()
        return value

    journal = {"rollback": release("0.1.0-dev.15", old), "target": release("0.1.0-dev.16", new)}
    recovery.write_record(cache / "meu-update-recovery.json", journal)
    homes = [home, home / "profiles" / "research"]
    for profile in homes:
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "config.yaml").write_text("model: old\n", encoding="utf-8")
        sql(profile / "state.db", "CREATE TABLE payload(value TEXT)")
        sql(profile / "state.db", "INSERT INTO payload VALUES('old')")
        sql(profile / "state.db", "CREATE TABLE runtime_epoch(singleton INTEGER PRIMARY KEY, epoch INTEGER, instance_id TEXT)")
        sql(profile / "state.db", "INSERT INTO runtime_epoch VALUES(1,2,'old')")
    return home, root, cache, key, old, new, git, facts, homes


def test_restores_code_profiles_schema_and_dependencies_preserving_failed_state(installation):
    home, root, cache, key, old, new, git, facts, homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    git("merge", "--ff-only", new)
    facts.write_text('{"new":true}', encoding="utf-8")
    for profile in homes:
        sql(profile / "state.db", "ALTER TABLE payload ADD COLUMN new_schema TEXT")
        sql(profile / "state.db", "UPDATE payload SET value='new'")
        sql(profile / "state.db", "UPDATE runtime_epoch SET epoch=9")
        (profile / "config.yaml").write_text("model: new\n", encoding="utf-8")
    record = recovery.restore(transaction)
    assert record["state"] == "restored"
    assert git("rev-parse", "HEAD") == old
    assert json.loads(facts.read_text(encoding="utf-8")) == {"old": True}
    for profile in homes:
        assert sql(profile / "state.db", "SELECT * FROM payload") == [("old",)]
        assert sql(profile / "state.db", "SELECT epoch FROM runtime_epoch") == [(9,)]
        assert (profile / "config.yaml").read_text(encoding="utf-8") == "model: old\n"
    with zipfile.ZipFile(transaction / "failed-state.zip") as archive:
        assert archive.read("config.yaml").decode().splitlines() == ["model: new"]
        assert "profiles/research/state.db" in archive.namelist()


def test_active_owner_blocks_recovery_before_changing_code_or_data(installation):
    home, root, cache, key, _old, new, git, _facts, _homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    git("merge", "--ff-only", new)
    owner = ProfileOwnership()
    owner.reserve([home])
    try:
        with pytest.raises(OwnershipConflict):
            recovery.restore(transaction)
    finally:
        owner.close()
    assert git("rev-parse", "HEAD") == new
    assert not (transaction / "failed-state.zip").exists()


@pytest.mark.parametrize("state", ["healthy", "cancelled", "failed"])
def test_monitor_tracks_the_real_parent_and_waits_for_a_matching_startup_receipt(installation, monkeypatch, state):
    home, root, cache, key, _old, new, _git, _facts, _homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    calls = []
    monkeypatch.setattr(watcher, "recover_installation", lambda *args: calls.append(args))
    child = subprocess.Popen([sys.executable, "-I", "-c", "import sys; sys.stdin.read()"],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    try:
        executable = Path(psutil.Process(child.pid).exe())

        def advance(_seconds):
            recovery.write_record(transaction / "signal.json", {"state": state, "commit": new, "version": "0.1.0-dev.16"})
            if state != "cancelled":
                child.stdin.close()
                child.wait(timeout=5)

        result = watcher.watch(transaction, child.pid, executable, "unused", wait=advance)
        assert result == ("rolled-back" if state == "failed" else state)
        assert bool(calls) == (state == "failed")
        if state == "cancelled":
            assert child.poll() is None
    finally:
        if not child.stdin.closed:
            child.stdin.close()
        child.wait(timeout=5)


def test_monitor_refuses_a_parent_from_another_executable(installation):
    home, root, cache, key, _old, _new, _git, _facts, _homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    with pytest.raises(ValueError, match="parent"):
        watcher.watch(transaction, os.getpid(), home / "other.exe", "unused")
    assert recovery.read_record(transaction / "transaction.json")["state"] == "prepared"


def test_work_completed_after_snapshot_is_preserved_without_replaying_it(installation):
    home, root, cache, key, _old, new, git, _facts, homes = installation
    sql(homes[1] / "state.db", "CREATE TABLE worker_receipts(execution_id TEXT, result_json TEXT)")
    transaction = recovery.prepare(root, home, cache, key, "git")
    git("merge", "--ff-only", new)
    sql(homes[1] / "state.db", "INSERT INTO worker_receipts VALUES('new-work','completed')")
    with pytest.raises(ValueError, match="New work"):
        recovery.restore(transaction)
    assert git("rev-parse", "HEAD") == new
    assert sql(homes[1] / "state.db", "SELECT * FROM worker_receipts") == [("new-work", "completed")]
    assert (transaction / "failed-state.zip").is_file()


def test_new_profile_database_blocks_rewind_without_discarding_it(installation):
    home, root, cache, key, _old, new, git, _facts, _homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    git("merge", "--ff-only", new)
    added = home / "new-work.db"
    sql(added, "CREATE TABLE work(value TEXT)")
    with pytest.raises(ValueError, match="new database"):
        recovery.restore(transaction)
    assert added.is_file()
    assert git("rev-parse", "HEAD") == new


def test_dependency_lock_contention_refuses_recovery_before_mutation(installation, monkeypatch):
    from hermes_cli import runtime_state
    from pm.environments import install_state_dir
    from pm.filesystem import lock_path
    home, root, cache, key, _old, new, git, _facts, _homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    git("merge", "--ff-only", new)
    fd = lock_path(install_state_dir(root) / ".install.lock", timeout=0, create_dir=True)
    assert fd is not None
    monkeypatch.setattr(recovery, "runtime_lock", lambda root: runtime_state.runtime_lock(root, timeout=0))
    try:
        with pytest.raises(TimeoutError, match="selection is busy"):
            recovery.restore(transaction)
    finally:
        os.close(fd)
    assert git("rev-parse", "HEAD") == new
    assert not (transaction / "failed-state.zip").exists()


def test_receipt_from_same_commit_but_another_version_does_not_disarm_monitor(tmp_path):
    recovery.write_record(tmp_path / "signal.json", {"state": "healthy", "commit": "a" * 40, "version": "0.1.0-dev.16"})
    with pytest.raises(ValueError, match="another build"):
        watcher.signal_state(tmp_path, "a" * 40, "0.1.0-dev.17")


def test_recovery_preserves_python_launcher_prefix_through_real_cli_calls(installation, monkeypatch):
    home, root, cache, key, old, _new, _git, _facts, _homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    record = recovery.read_record(transaction / "transaction.json")
    calls = home / "cli-calls.jsonl"
    script = home / "backend cli.py"
    script.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "assert sys.argv[1:3]==['--fixture','owned']\n"
        f"assert os.environ['HERMES_HOME']=={str(home)!r}\n"
        f"with Path({str(calls)!r}).open('a',encoding='utf-8') as f: f.write(json.dumps(sys.argv[3:])+'\\n')\n"
        f"print(json.dumps({{'state':'ready','client_code_sha':{old!r},'endpoint':{{'code_sha':{old!r}}}}}))\n",
        encoding="utf-8")
    monkeypatch.setattr(recovery, "restore", lambda *_args, **_kwargs: record)
    installer = cache / record["rollback"]["file"]
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        if command[0] == str(installer):
            return subprocess.CompletedProcess(command, 17)  # Never execute fixture bytes.
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(watcher.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Previous Meu installer failed|Windows only"):
        watcher.recover_installation(transaction, root / "Meu.exe", sys.executable, 0,
                                     ["-I", str(script), "--fixture", "owned"])
    assert [json.loads(line) for line in calls.read_text(encoding="utf-8-sig").splitlines()] == [
        ["gateway", "stop"], ["gateway", "ensure", "--json"], ["gateway", "stop"]]


@pytest.mark.parametrize("damage", ["archive", "installer", "signature", "source"])
def test_refuses_damaged_recovery_or_user_source_edits_before_mutation(installation, damage):
    home, root, cache, key, _old, new, git, _facts, _homes = installation
    transaction = recovery.prepare(root, home, cache, key, "git")
    git("merge", "--ff-only", new)
    if damage == "archive":
        (transaction / "before.zip").write_bytes(b"broken archive")
    elif damage == "installer":
        (cache / "Meu-0.1.0-dev.15-win-x64.exe").write_bytes(b"wrong bytes")
    elif damage == "signature":
        record = recovery.read_record(transaction / "transaction.json")
        record["rollback"]["commit"] = "f" * 40
        recovery.write_record(transaction / "transaction.json", record)
    else:
        (root / "backend.py").write_text("user_work = True\n", encoding="utf-8")
    with pytest.raises((ValueError, InvalidSignature)):
        recovery.restore(transaction)
    assert git("rev-parse", "HEAD") == new
    assert not (transaction / "failed-state.zip").exists()
