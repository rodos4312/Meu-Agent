"""Operator editing of project notes through the existing transactional memory store."""

from hashlib import sha256

from tools.project_memory import note_id


def snapshot(store) -> dict:
    if not store.target_enabled("project"):
        return {"enabled": False, "root": None, "path": None, "revision": "", "entries": [],
                "limit": store.memory_char_limit}
    path = store._path_for("project")
    with store._file_lock(path):
        raw, okay = store._read_raw_checked(path)
        if not okay:
            raise OSError("Project notes could not be read; no changes were made.")
        entries = list(dict.fromkeys(store._parse_entries(raw)))
    return {"enabled": True, "root": str(store.project_scope.root), "path": str(path),
            "revision": sha256(raw.encode("utf-8")).hexdigest(), "limit": store.memory_char_limit,
            "entries": [{"id": note_id(entry), "content": entry} for entry in entries]}


def update(store, params: dict) -> dict:
    current = snapshot(store)
    if not current["enabled"]:
        raise ValueError("Project notes are disabled in memory settings or the project folder is unavailable.")
    action = params["action"]
    operation = {"action": action, "content": params.get("content", "")}
    if action != "add":
        entry = next((entry for entry in current["entries"] if entry["id"] == params.get("note_id")), None)
        if entry is None:
            return {"memory": current, "saved": False, "conflict": True,
                    "error": "This note changed or was removed. Reload the notes before editing."}
        operation.update(old_text=entry["content"], matched_entry=entry["content"])
    # User edits are explicit operator actions, like /memory restore. Agent approval
    # settings do not create a second confirmation, and their defaults are untouched.
    result = store.apply_batch("project", [operation], expected_revision=params["revision"])
    error = result.get("error")
    if not result["success"]:
        from tools.memory_tool import FAILURE_CLASS

        if FAILURE_CLASS.get() == "over_budget":
            error = f"These notes exceed the {current['limit']}-character limit. Shorten a note before saving."
    return {"memory": snapshot(store), "saved": result["success"],
            "conflict": result.get("conflict", False), "error": error}
