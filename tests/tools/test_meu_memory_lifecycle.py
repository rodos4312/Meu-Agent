"""Persistent memory, corrections and operator rollback with unchanged approval policy."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from hermes_cli.write_approval_commands import handle_pending_subcommand
from tools.memory_history import memory_versions, memory_version_diff, restore_memory_version
from tools.memory_tool import MemoryStore, get_memory_dir, memory_tool


def _store():
    store = MemoryStore()
    store.load_from_disk()
    return store


def _restarted_user_memory():
    script = (
        "from tools.memory_tool import MemoryStore; s=MemoryStore(); "
        "s.load_from_disk(); print(s.format_for_system_prompt('user'))"
    )
    return subprocess.check_output([sys.executable, "-c", script], env=dict(os.environ), text=True, encoding="utf-8")


def test_memory_correction_restart_and_rollback_keep_the_active_prompt_frozen():
    first = _store()
    assert first.add("user", "Η προτιμώμενη γλώσσα είναι τα ελληνικά.")["success"]
    next_session = _store()
    snapshot = next_session.format_for_system_prompt("user")
    assert "ελληνικά" in snapshot
    assert next_session.patch("user", "ελληνικά", "ισπανικά")["success"]
    assert next_session.format_for_system_prompt("user") == snapshot
    assert "ισπανικά" in _restarted_user_memory()
    versions = [v for v in memory_versions(get_memory_dir()) if v["target"] == "user"]
    previous = versions[0]["id"]
    assert "ελληνικά" in memory_version_diff(get_memory_dir(), previous)
    restore_memory_version(next_session, previous)
    assert next_session.format_for_system_prompt("user") == snapshot
    assert "ελληνικά" in _store().format_for_system_prompt("user")
    assert "ισπανικά" not in _store().format_for_system_prompt("user")
    assert "ελληνικά" in _restarted_user_memory()


def test_history_uses_the_active_profile_and_rejects_paths(tmp_path, monkeypatch):
    home = tmp_path / "one"
    monkeypatch.setenv("HERMES_HOME", str(home))
    store = _store()
    assert store.add("memory", "First profile fact")["success"]
    version = memory_versions(get_memory_dir())[0]["id"]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "two"))
    assert memory_versions(get_memory_dir()) == []
    with pytest.raises(FileNotFoundError):
        restore_memory_version(_store(), version)
    with pytest.raises(ValueError):
        restore_memory_version(_store(), "../../one/memories/MEMORY.md")


def test_failed_write_preserves_disk_and_live_entries(monkeypatch):
    store = _store()
    assert store.add("memory", "Original fact")["success"]
    path = get_memory_dir() / "MEMORY.md"
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("tools.memory_tool_store.atomic_write_text", fail)
    outcome = store.patch("memory", "Original", "Changed")
    assert outcome["success"] is False
    assert path.read_bytes() == before
    assert store.memory_entries == ["Original fact"]


def test_history_is_bounded_and_concurrent_updates_keep_every_entry():
    store = _store()
    for index in range(55):
        assert store.add("memory", f"Fact {index}")["success"]
    assert len(memory_versions(get_memory_dir())) == 50

    def add(index):
        return _store().add("user", f"Concurrent fact {index}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(r["success"] for r in pool.map(add, range(8)))
    assert len(_store().user_entries) == 8


def test_inspection_commands_work_without_a_new_approval_prompt():
    store = _store()
    assert store.add("memory", "Remembered fact")["success"]
    assert "Remembered fact" in handle_pending_subcommand("memory", ["show"], memory_store=store)
    history = handle_pending_subcommand("memory", ["history"], memory_store=store)
    version = history.split()[0]
    assert "Remembered fact" in handle_pending_subcommand("memory", ["diff", version], memory_store=store)
    assert "Restored" in handle_pending_subcommand("memory", ["restore", version], memory_store=store)
    assert _store().memory_entries == []


@pytest.mark.parametrize("config", [{}, {"memory": {"write_approval": False}}])
def test_memory_tool_preserves_the_existing_autonomous_setting(tmp_path, monkeypatch, config):
    from hermes_cli.config_backend import write_config_document

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_config_document(tmp_path / "config.yaml", config)
    store = _store()
    result = json.loads(memory_tool(action="add", target="memory", content="Saved automatically", store=store))
    assert result["success"] is True
    assert not result.get("staged")
    assert _store().memory_entries == ["Saved automatically"]
    assert not (tmp_path / "pending").exists()
