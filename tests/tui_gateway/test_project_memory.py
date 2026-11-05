"""Desktop memory inspection retains workspace scope without a resident agent."""

from hermes_cli.write_approval_commands import handle_pending_subcommand
from tools.memory_tool import MemoryStore, apply_memory_pending
from tui_gateway.methods_tools import _pending_subcommand_store


def test_desktop_memory_commands_use_selected_folder_without_live_agent(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    store = MemoryStore(project_cwd=str(folder))
    store.load_from_disk()
    assert store.add("project", "Export birthday cards as PNG.")["success"]

    session = {"agent": None, "cwd": str(folder), "explicit_cwd": True}
    loaded = _pending_subcommand_store(session)
    assert loaded is not None
    assert "Export birthday cards" in handle_pending_subcommand("memory", ["show", "project"], memory_store=loaded)
    payload = {"action": "add", "target": "project", "content": "Use A5.", "project_scope": store.project_scope.key}
    assert apply_memory_pending(payload, loaded)["success"]

    no_workspace = _pending_subcommand_store({"agent": None, "cwd": str(folder), "explicit_cwd": False})
    assert no_workspace is not None
    assert not no_workspace.target_enabled("project")
    assert no_workspace.memory_entries == []
