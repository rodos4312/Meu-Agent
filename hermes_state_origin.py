"""Where a chat was created: one ``state_meta`` row per session, written once at creation.

The row is the only source of truth. Nothing here infers an origin from ``source`` or
from the pairing, so chats that existed before the row was introduced stay unmarked.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

ORIGIN_PREFIX = "meu.origin.session:"
_KINDS = frozenset({"phone"})
_MAX_DEVICE = 80


def origin_value(origin: dict | None) -> str | None:
    """Canonical stored JSON, or None when there is nothing valid to record."""
    if not isinstance(origin, dict) or origin.get("kind") not in _KINDS:
        return None
    device = origin.get("device")
    device = device.strip()[:_MAX_DEVICE] if isinstance(device, str) else ""
    return json.dumps({"kind": origin["kind"], "device": device}, ensure_ascii=False, separators=(",", ":"))


def record_origin(conn, session_id: str, origin: dict | None) -> None:
    """Insert-only inside the caller's transaction: a later write never replaces the first origin."""
    value = origin_value(origin)
    if value is not None:
        conn.execute("INSERT OR IGNORE INTO state_meta (key, value) VALUES (?, ?)",
                     (ORIGIN_PREFIX + session_id, value))


def read_origins(db, session_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ids = [sid for sid in dict.fromkeys(session_ids) if isinstance(sid, str) and sid]
    found: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for row in db._read_all(
                f"SELECT key, value FROM state_meta WHERE key IN ({marks})",
                [ORIGIN_PREFIX + sid for sid in chunk]):
            try:
                value = json.loads(row["value"])
            except ValueError:
                continue
            if isinstance(value, dict) and value.get("kind") in _KINDS:
                found[row["key"][len(ORIGIN_PREFIX):]] = {
                    "kind": value["kind"], "device": str(value.get("device") or "")}
    return found
