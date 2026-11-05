"""Portable project notes retain history without mixing copied projects or profiles."""
import hashlib
import json
import os
import shutil

from tools.memory_tool import MemoryStore


def store(root):
    result = MemoryStore(project_cwd=str(root))
    result.load_from_disk()
    return result


def test_notes_and_history_follow_folder_rename_and_move(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    before = store(original)
    initial_prompt = before.format_for_system_prompt("project")
    assert before.add("project", "Use SQLite for this project.")["success"]
    first_snapshot = store(original).format_for_system_prompt("project")
    assert before.apply_batch("project", [{"action": "patch", "old_text": "SQLite", "content": "PostgreSQL"}])["success"]
    history = sorted(before.project_scope.directory.glob("**/*"))
    moved = tmp_path / "new-parent" / "renamed"
    moved.parent.mkdir()
    original.rename(moved)
    after = store(moved)
    assert after.project_scope.directory == before.project_scope.directory
    assert after.project_entries == ["Use PostgreSQL for this project."]
    assert sorted(after.project_scope.directory.glob("**/*")) == history
    assert "SQLite" in first_snapshot
    assert before.format_for_system_prompt("project") == initial_prompt


def test_copy_of_live_project_gets_independent_notes(tmp_path):
    original, copied = tmp_path / "source", tmp_path / "copy"
    original.mkdir()
    first = store(original)
    assert first.add("project", "Source-private convention.")["success"]
    shutil.copytree(original, copied)
    second = store(copied)
    assert second.project_scope.directory != first.project_scope.directory
    assert second.project_entries == []
    assert second.add("project", "Copy-specific convention.")["success"]
    assert store(original).project_entries == ["Source-private convention."]
    assert store(copied).project_entries == ["Copy-specific convention."]


def test_reusing_a_moved_projects_old_path_does_not_reuse_its_notes(tmp_path):
    original, moved = tmp_path / "original", tmp_path / "moved"
    original.mkdir()
    assert store(original).add("project", "Only the moved project may read this.")["success"]
    original.rename(moved)
    assert store(moved).project_entries == ["Only the moved project may read this."]
    original.mkdir()
    assert store(original).project_entries == []
    assert store(original).add("project", "An entirely new project.")["success"]
    assert store(moved).project_entries == ["Only the moved project may read this."]
    assert store(original).project_entries == ["An entirely new project."]


def test_copy_back_to_original_path_keeps_moved_project_independent(tmp_path):
    original, moved = tmp_path / "original", tmp_path / "moved"
    original.mkdir()
    assert store(original).add("project", "The moved project's convention.")["success"]
    original.rename(moved)
    store(moved)
    shutil.copytree(moved, original)
    assert store(original).project_entries == []
    assert store(original).add("project", "The copied project's convention.")["success"]
    assert store(moved).project_entries == ["The moved project's convention."]


def test_legacy_notes_are_anchored_without_moving_or_rewriting_them(tmp_path, monkeypatch):
    root = tmp_path / "legacy"
    root.mkdir()
    home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    legacy = hashlib.sha256(("folder:" + os.path.normcase(str(root.resolve()))).encode()).hexdigest()[:24]
    directory = home / "memories/projects" / legacy
    directory.mkdir(parents=True)
    notes = directory / "PROJECT.md"
    notes.write_text("Legacy note.\n", encoding="utf-8")
    original = notes.read_bytes()
    assert store(root).project_entries == ["Legacy note."]
    moved = tmp_path / "moved"
    root.rename(moved)
    assert store(moved).project_entries == ["Legacy note."]
    assert notes.read_bytes() == original


def test_registered_project_keeps_notes_when_primary_folder_changes(tmp_path):
    from hermes_cli import projects_db
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    with projects_db.connect_closing() as conn:
        project = projects_db.create_project(conn, name="Workspace", folders=[str(one), str(two)])
    before = store(one)
    assert before.add("project", "A shared workspace fact.")["success"]
    with projects_db.connect_closing() as conn:
        assert projects_db.set_primary(conn, project, str(two))
    after = store(two)
    assert after.project_scope.directory == before.project_scope.directory
    assert after.project_entries == ["A shared workspace fact."]


def test_marker_does_not_share_notes_across_profiles(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile-one"))
    assert store(root).add("project", "Profile one only.")["success"]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile-two"))
    assert store(root).project_entries == []
    assert store(root).add("project", "Profile two only.")["success"]
    moved = tmp_path / "renamed"
    root.rename(moved)
    assert store(moved).project_entries == ["Profile two only."]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile-one"))
    assert store(moved).project_entries == ["Profile one only."]


def test_reading_empty_project_does_not_create_project_metadata(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    assert store(root).project_entries == []
    assert list(root.iterdir()) == []


def test_forged_marker_cannot_select_another_projects_existing_notes(tmp_path):
    from tools.project_memory_identity import MARKER
    original, other = tmp_path / "original", tmp_path / "other"
    original.mkdir()
    other.mkdir()
    assert store(original).add("project", "Keep this private to the original project.")["success"]
    marker = json.loads((original / MARKER).read_text())
    original.rename(tmp_path / "hidden-original")
    marker["token"] = "0" * 64
    (other / MARKER.parent).mkdir()
    (other / MARKER).write_text(json.dumps(marker))
    assert store(other).project_entries == []


def test_malformed_marker_is_not_replaced_and_global_notes_still_work(tmp_path):
    from tools.project_memory_identity import MARKER
    root = tmp_path / "project"
    root.mkdir()
    before = store(root)
    assert before.add("project", "An existing project note.")["success"]
    marker = root / MARKER
    marker.write_text("user-owned or corrupted content")
    after = store(root)
    assert after.project_entries == ["An existing project note."]
    assert not after.add("project", "Refuse this write.")["success"]
    assert after.add("user", "General preference remains usable.")["success"]
    assert marker.read_text() == "user-owned or corrupted content"


def test_profile_index_can_restore_a_missing_marker_at_the_same_location(tmp_path):
    from tools.project_memory_identity import MARKER
    root = tmp_path / "project"
    root.mkdir()
    assert store(root).add("project", "Keep this note.")["success"]
    moved = tmp_path / "moved"
    root.rename(moved)
    before = store(moved)
    (moved / MARKER).unlink()
    after = store(moved)
    assert after.project_scope.directory == before.project_scope.directory
    assert after.project_entries == ["Keep this note."]


def test_parallel_profile_claims_keep_one_portable_marker(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from tools.project_memory_identity import MARKER, identity_directory
    root = tmp_path / "shared-folder"
    root.mkdir()
    legacy = hashlib.sha256(("folder:" + os.path.normcase(str(root))).encode()).hexdigest()[:24]
    homes = [tmp_path / "profile-one", tmp_path / "profile-two"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(lambda home: identity_directory(root, home, legacy, create=True), homes))
    marker = json.loads((root / MARKER).read_text())
    for home, directory in zip(homes, paths):
        records = json.loads((home / "memories/project-identities.json").read_text())["records"]
        assert records[directory.name]["token"] == marker["token"]
