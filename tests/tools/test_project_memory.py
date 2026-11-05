"""Project notes survive restart, stay local and never cross workspace/profile boundaries."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from agent.agent_init import _init_memory
from agent.inline_tool_executors import INLINE_TOOL_EXECUTORS, InlineToolContext
from agent.system_prompt import _memory_parts
from hermes_cli.memory_history_commands import handle_memory_history
from tools.memory_tool import MemoryStore, apply_memory_pending, memory_tool


def _store(folder, **kwargs):
    store = MemoryStore(project_cwd=str(folder) if folder else None, **kwargs)
    store.load_from_disk()
    return store


def _write(store, **kwargs):
    return json.loads(memory_tool(target="project", store=store, **kwargs))


def test_project_notes_restart_correction_history_and_frozen_prompt(tmp_path):
    folder = tmp_path / "Birthday card"
    folder.mkdir()
    store = _store(folder)
    result = _write(store, action="add", content="Κάρτα σε PNG, μέγεθος A5.")
    assert result["success"], result
    snapshot = _store(folder)
    frozen = snapshot.format_for_system_prompt("project")
    assert "μέγεθος A5" in frozen
    assert _write(snapshot, action="patch", old_text="A5", content="A4")["success"]
    assert snapshot.format_for_system_prompt("project") == frozen
    script = ("import sys; from tools.memory_tool import MemoryStore; "
              "s=MemoryStore(project_cwd=sys.argv[1]); s.load_from_disk(); "
              "print(s.format_for_system_prompt('project'))")
    restarted = subprocess.check_output([sys.executable, "-c", script, str(folder)],
                                        env=dict(os.environ), text=True, encoding="utf-8")
    assert "μέγεθος A4" in restarted and "μέγεθος A5" not in restarted
    history = handle_memory_history(["history", "project"], snapshot)
    version = history.split()[0]
    assert "A5" in handle_memory_history(["diff", "project", version], snapshot)
    assert "Restored" in handle_memory_history(["restore", "project", version], snapshot)
    assert "μέγεθος A5" in _store(folder).format_for_system_prompt("project")
    assert snapshot.format_for_system_prompt("project") == frozen


def test_two_projects_and_profiles_are_isolated(tmp_path, monkeypatch):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    first = _store(one)
    assert _write(first, action="add", content="Project one uses SQLite.")["success"]
    assert first.add("user", "Prefers Greek.")["success"]
    second = _store(two)
    assert "SQLite" not in second.format_for_system_prompt("project")
    assert "Prefers Greek" in second.format_for_system_prompt("user")
    assert second.memory_entries == []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "another-profile"))
    other_profile = _store(one)
    assert other_profile.project_entries == []
    assert other_profile.user_entries == []
    assert not _write(first, action="add", content="Wrong scope.")["success"]


def test_git_subfolders_and_registered_project_folders_share_notes(tmp_path):
    from contextlib import closing
    from hermes_cli import projects_db

    root, extra = tmp_path / "repo", tmp_path / "extra"
    child = root / "src"
    child.mkdir(parents=True)
    extra.mkdir()
    (root / ".git").mkdir()
    assert _write(_store(root), action="add", content="Git project fact.")["success"]
    assert _store(child).project_entries == ["Git project fact."]
    with closing(projects_db.connect()) as conn:
        projects_db.create_project(conn, name="Multi-folder", folders=[str(root), str(extra)])
    assert _write(_store(child), action="add", content="Registered project fact.")["success"]
    assert _store(extra).project_entries == ["Git project fact.", "Registered project fact."]


@pytest.mark.parametrize("enabled", [True, False])
def test_no_selected_project_never_falls_back_to_global_notes(enabled):
    store = _store(None, memory_enabled=enabled)
    assert not _write(store, action="add", content="Must not become a global note.")["success"]
    assert store.memory_entries == []
    assert store.format_for_system_prompt("project") is None


def test_pending_write_is_bound_to_original_project(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    first, second = _store(one), _store(two)
    payload = {"action": "add", "target": "project", "content": "Only one.",
               "project_scope": first.project_scope.key}
    assert not apply_memory_pending(payload, second)["success"]
    assert apply_memory_pending(payload, first)["success"]
    assert _store(one).project_entries == ["Only one."]
    assert _store(two).project_entries == []


def test_parallel_project_writes_keep_all_entries(tmp_path):
    folder = tmp_path / "concurrent"
    folder.mkdir()
    stores = [_store(folder) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda pair: _write(pair[1], action="add", content=f"Fact {pair[0]}"),
                                    enumerate(stores)))
    assert all(result["success"] for result in results)
    assert set(_store(folder).project_entries) == {f"Fact {i}" for i in range(4)}


def test_staged_project_correction_pins_scope_and_original_entry(tmp_path):
    from tools.skill_provenance import reset_current_write_origin, set_current_write_origin
    from tools.write_approval import MEMORY, get_pending

    folder = tmp_path / "staging"
    folder.mkdir()
    store = _store(folder)
    assert _write(store, action="add", content="Use A5 cards.")["success"]
    token = set_current_write_origin("background_review")
    try:
        result = _write(store, operations=[{"action": "patch", "old_text": "A5", "content": "A4"}])
    finally:
        reset_current_write_origin(token)
    assert result["staged"]
    record = get_pending(MEMORY, result["pending_id"])
    assert record["payload"]["project_scope"] == store.project_scope.key
    assert _store(folder).project_entries == ["Use A5 cards."]
    assert apply_memory_pending(record["payload"], _store(folder))["success"]
    assert _store(folder).project_entries == ["Use A4 cards."]


def test_agent_startup_injection_and_inline_write_stay_local(tmp_path):
    folder = tmp_path / "actual-agent-workspace"
    folder.mkdir()
    agent = SimpleNamespace(session_cwd=str(folder), enabled_toolsets=["memory"], disabled_toolsets=[])
    _init_memory(agent, {}, True, "desktop")
    assert "PROJECT MEMORY" in "\n".join(_memory_parts(agent))

    def unexpected_mirror(*args, **kwargs):
        pytest.fail("Project notes must not be mirrored to an external memory provider")

    agent._memory_manager = SimpleNamespace(notify_memory_tool_write=unexpected_mirror)
    context = InlineToolContext(effective_task_id="task", tool_call_id="call")
    result = json.loads(INLINE_TOOL_EXECUTORS["memory"](agent, {
        "target": "project", "operations": [{"action": "add", "content": "Use a local PNG renderer."}],
    }, context))
    assert result["success"] and not result.get("staged")
    next_agent = SimpleNamespace(session_cwd=str(folder), enabled_toolsets=["memory"], disabled_toolsets=[])
    _init_memory(next_agent, {}, True, "desktop")
    assert "Use a local PNG renderer" in "\n".join(_memory_parts(next_agent))
