"""The parent chooses relevant notes; native helper contexts never get other notes."""

from tools.memory_tool import load_on_disk_store
from tests.plugins.delegation.test_meu_coordinator import task
from tests.plugins.delegation.test_meu_projects import create, project


def test_helpers_only_receive_selected_project_notes(coordinator, tmp_path):
    _home, built, parent = coordinator
    root = tmp_path / "workspace"
    root.mkdir()
    memory = load_on_disk_store(project_cwd=str(root))
    assert memory.add("project", "Images use PNG at A5 size.")["success"]
    assert memory.add("project", "Reports use EUR amounts.")["success"]
    initial = create(parent, root, [task(id="image"), task("complex", ["report.txt"], id="report")])
    notes = {note["content"]: note["id"] for note in initial["memory_notes"]}
    result = project(parent, "run", task_memory={
        "image": [notes["Images use PNG at A5 size."]], "report": [notes["Reports use EUR amounts."]],
    })
    assert result["tasks"]["image"]["state"] == "needs_review", result
    assert "Images use PNG" in built[0]["context"] and "EUR" not in built[0]["context"]
    assert "Reports use EUR" in built[1]["context"] and "A5" not in built[1]["context"]
    assert result["tasks"]["image"]["memory_used"] == [initial["memory_notes"][0]]


def test_changed_note_refuses_before_starting_helpers(coordinator, tmp_path):
    _home, built, parent = coordinator
    root = tmp_path / "workspace"
    root.mkdir()
    memory = load_on_disk_store(project_cwd=str(root))
    assert memory.add("project", "Use A5.")["success"]
    created = create(parent, root, [task(id="image")])
    old_id = created["memory_notes"][0]["id"]
    assert memory.patch("project", "A5", "A4")["success"]
    result = project(parent, "run", task_memory={"image": [old_id]})
    assert "changed or is unavailable" in result["error"]
    assert built == []
    status = project(parent, "status")
    assert status["tasks"]["image"]["attempt"] == 0
    assert status["tasks"]["image"]["state"] == "pending"
    assert status["memory_notes"][0]["content"] == "Use A4."


def test_disabled_notes_are_not_exposed_to_coordinator(coordinator, tmp_path):
    _home, built, parent = coordinator
    root = tmp_path / "workspace"
    root.mkdir()
    assert load_on_disk_store(project_cwd=str(root)).add("project", "Private project fact.")["success"]
    parent._memory_enabled = False
    created = create(parent, root, [task(id="inspect")])
    assert created["memory_notes"] == []
    assert project(parent, "run")["tasks"]["inspect"]["state"] == "needs_review"
    assert "Private project fact" not in built[0]["context"]
