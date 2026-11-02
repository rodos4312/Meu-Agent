"""Operator-only inspection and rollback through the existing /memory command."""

from __future__ import annotations

from datetime import UTC, datetime


def _history_line(record: dict) -> str:
    date = datetime.fromtimestamp(record["created_ns"] / 1_000_000_000, tz=UTC).isoformat(timespec="seconds")
    label = {"memory": "Agent notes", "user": "User profile"}[record["target"]]
    return f"{record['id'][:8]}  {date}  {label}"


def handle_memory_history(args: list[str], store) -> str | None:
    if not args or args[0].lower() not in {"show", "history", "diff", "restore"}:
        return None
    from tools.memory_tool import get_memory_dir, load_on_disk_store
    from tools.memory_history import memory_version_diff, memory_versions, restore_memory_version

    store = store or load_on_disk_store()
    command, rest = args[0].lower(), args[1:]
    if command in {"diff", "restore"} and len(rest) != 1:
        return f"Usage: /memory {command} <version-id>"
    handlers = {
        "show": lambda: "\n\n".join(
            f"{label}\n" + "\n".join(store._entries_for(target))
            for target, label in (("memory", "Agent notes"), ("user", "User profile"))),
        "history": lambda: "\n".join(
            _history_line(r) for r in memory_versions(get_memory_dir())) or "No memory versions yet.",
        "diff": lambda: memory_version_diff(get_memory_dir(), rest[0]),
        "restore": lambda: restore_memory_version(store, rest[0]),
    }
    try:
        return handlers[command]()
    except (OSError, ValueError, RuntimeError) as exc:
        return f"Memory {command} failed; no restoration was applied: {exc}"
