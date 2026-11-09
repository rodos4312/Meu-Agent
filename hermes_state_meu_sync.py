"""Read a settled sync transcript without publishing a writer's partial reply."""
from contextlib import contextmanager
from hashlib import sha256
import json
import re
import time

from hermes_state_errors import SessionActiveWriteGuardError
from hermes_state_messages import _stale_holder


@contextmanager
def sync_snapshot(db):
    """Keep authorization, lease checks and transcript on one SQLite generation."""
    with db._read_ctx() as conn:
        owned = not conn.in_transaction
        if owned:
            conn.execute("BEGIN")
        try:
            yield conn
        finally:
            if owned and conn.in_transaction:
                conn.execute("ROLLBACK")


def require_quiet(db, conn, session_id):
    """A read never clears stale leases or imports an uncommitted response."""
    conversation_id = db._session_turn_lease_key_on_conn(conn, session_id)
    guards = [
        conn.execute(
            "SELECT holder, expires_at FROM session_turn_leases WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone(),
        conn.execute(
            "SELECT holder, expires_at FROM compression_locks WHERE session_id = ?",
            (session_id,),
        ).fetchone(),
    ]
    if any(row is not None and not _stale_holder(row, time.time()) for row in guards):
        raise SessionActiveWriteGuardError("Conversation is still being written")
    pending = conn.execute(
        "SELECT 1 FROM session_admissions WHERE target_session_id = ? "
        "AND status IN ('queued', 'started', 'unknown') UNION ALL "
        "SELECT 1 FROM worker_executions WHERE session_id = ? "
        "AND status IN ('registered', 'running', 'unknown') LIMIT 1",
        (session_id, session_id),
    ).fetchone()
    if pending is not None:
        raise SessionActiveWriteGuardError("Conversation has unfinished work")


def fingerprint(history):
    messages = [{key: row[key] for key in ("role", "content", "message_uid")}
                for row in history["messages"]]
    return sha256(json.dumps(messages, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _scope(db, conn, session_id, personal_space):
    if not isinstance(session_id, str) or not db._MEU_SYNC_SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid sync session")
    if personal_space is not None:
        db._meu_require_space(conn, session_id, personal_space)
    row = conn.execute(
        f"SELECT started_at, title, ({db._MEU_SYNC_PROFILE_SCOPE}) AS allowed FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None or not row["allowed"]:
        raise LookupError("Session unavailable")
    return row


def _validate_recovery(db, request):
    if not isinstance(request, dict) or set(request) != {"pc", "phone", "prefer", "expected"}:
        raise ValueError("Invalid recovery request")
    if request["prefer"] not in ("pc", "phone") or not isinstance(request["expected"], str):
        raise ValueError("Invalid recovery choice")
    if not re.fullmatch(r"[0-9a-f]{64}", request["expected"]):
        raise ValueError("Invalid recovery version")
    for side in ("pc", "phone"):
        history = request[side]
        if not isinstance(history, dict):
            raise ValueError("Invalid recovery history")
        fields = {"id", "messages"} | ({"started_at"} if "started_at" in history else set())
        if set(history) != fields:
            raise ValueError("Recovery accepts visible text only")
        timestamps = "started_at" in history
        if timestamps:
            db._meu_sync_timestamp(history["started_at"])
        db._validate_meu_sync_text(history["messages"], timestamps=timestamps)
    sid = request["pc"]["id"]
    if (not isinstance(sid, str) or not db._MEU_SYNC_SESSION_ID.fullmatch(sid)
            or sid != request["phone"]["id"]):
        raise ValueError("Recovery histories must name the same session")
    versions = {side: fingerprint(request[side]) for side in ("pc", "phone")}
    if request["expected"] not in versions.values():
        raise ValueError("Expected version is outside this recovery")
    receipt = sha256(json.dumps({"id": sid, "prefer": request["prefer"], **versions},
                               sort_keys=True).encode("ascii")).hexdigest()
    return sid, receipt


def _replace_visible_tail(db, conn, sid, before, chosen):
    common = 0
    for current, preferred in zip(before["messages"], chosen["messages"]):
        if any(current[key] != preferred[key] for key in ("role", "content", "message_uid")):
            break
        common += 1
    if common == len(before["messages"]) == len(chosen["messages"]):
        return
    # Keep all internal rows in the shared prefix, including tool results. The
    # replaced suffix is soft-archived by the standard rewind persistence API.
    rows = conn.execute("SELECT * FROM messages WHERE session_id = ? AND active = 1 ORDER BY id LIMIT 20001", (sid,)).fetchall()
    if len(rows) > 20000:
        raise ValueError("Recovery transcript is too large")
    boundary = None
    if common < len(before["messages"]):
        uid = before["messages"][common]["message_uid"]
        boundary = conn.execute(
            "SELECT id FROM messages WHERE session_id = ? AND active = 1 "
            "AND message_uid = ? AND role IN ('user', 'assistant') "
            "AND _compressed_summary = 0 AND coalesce(display_kind, '') = '' ORDER BY id LIMIT 1",
            (sid, uid),
        ).fetchone()[0]
    prefix = [db._row_to_message_dict(row, warn_context="sync recovery", summary_flag=True)
              for row in rows if boundary is None or row["id"] < boundary]
    db.replace_messages_in_transaction(
        conn, sid, [*prefix, *(dict(row) for row in chosen["messages"][common:])], archive_dropped=True,
        reject_active_turn_lease=True, expected_active_ids=[row["id"] for row in rows],
    )


def resolve_history(db, request, *, personal_space=None):
    """An explicit, version-bound choice; save both copies before a soft rewind."""
    sid, receipt = _validate_recovery(db, request)
    chosen = request[request["prefer"]]
    key = "meu.sync.backup:" + sid + ":" + receipt

    def apply(conn):
        row = _scope(db, conn, sid, personal_space)
        require_quiet(db, conn, sid)
        before = {"id": sid, "messages": db._meu_sync_text(conn, sid, timestamps=True),
                  "started_at": row["started_at"]}
        current = fingerprint(before)
        saved = conn.execute("SELECT value FROM state_meta WHERE key = ?", (key,)).fetchone()
        if saved is not None:
            return ({"status": "resolved", "receipt": receipt}
                    if current == fingerprint(chosen) else {"status": "stale"})
        if current != request["expected"]:
            return {"status": "stale"}
        if saved is None:
            record = {"id": sid, "receipt": receipt, "created_at": time.time(),
                      "prefer": request["prefer"], "pc": request["pc"], "phone": request["phone"],
                      "local_before": before}
            conn.execute("INSERT INTO state_meta(key, value) VALUES (?, ?)",
                         (key, json.dumps(record, ensure_ascii=True)))
        _replace_visible_tail(db, conn, sid, before, chosen)
        if fingerprint({"messages": db._meu_sync_text(conn, sid)}) != fingerprint(chosen):
            raise ValueError("Recovery did not preserve the chosen history")
        if current != fingerprint(chosen):
            conn.execute("INSERT OR REPLACE INTO state_meta(key, value) VALUES (?, ?)",
                         ("meu.sync.revision:" + sid, receipt))
        return {"status": "resolved", "receipt": receipt}

    return db._execute_write(apply)


def history_stamp(db, session_id, message_count):
    """Preserve count-based caching, but distinguish an explicit same-length rewind."""
    with db._read_ctx() as conn:
        row = conn.execute("SELECT value FROM state_meta WHERE key = ?",
                           ("meu.sync.revision:" + session_id,)).fetchone()
    return (message_count, row[0]) if row else message_count


def adopt_recovered_history(db, session, session_id, ceiling):
    """Refresh a warm desktop/mobile session after an explicit sync recovery."""
    with session["history_lock"]:
        version = int(session.get("history_version", 0))
        observed = session.get("_meu_sync_revision")
    with sync_snapshot(db) as conn:
        row = conn.execute("SELECT value FROM state_meta WHERE key = ?",
                           ("meu.sync.revision:" + session_id,)).fetchone()
        if row is None or row[0] == observed:
            return False
        history = db.get_messages_as_conversation(
            session_id, repair_alternation=True, include_row_ids=True)
        if ceiling is not None:
            history = [message for message in history if message.get("_row_id", ceiling) < ceiling]
    with session["history_lock"]:
        if int(session.get("history_version", 0)) != version:
            raise RuntimeError("Conversation changed while loading sync recovery; retry the turn")
        session["history"] = history
        session["history_version"] = version + 1
        session["_meu_sync_revision"] = row[0]
    return True


def recovery_backups(db, *, session_id=None, receipt=None, personal_space=None):
    if receipt is not None and (not isinstance(receipt, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt)):
        raise ValueError("Invalid recovery receipt")
    with sync_snapshot(db) as conn:
        if session_id is not None:
            _scope(db, conn, session_id, personal_space)
        if receipt is not None:
            if session_id is None:
                raise ValueError("A backup belongs to a session")
            row = conn.execute("SELECT value FROM state_meta WHERE key = ?",
                               ("meu.sync.backup:" + session_id + ":" + receipt,)).fetchone()
            if row is None:
                raise LookupError("Backup unavailable")
            return json.loads(row[0])
        if personal_space is not None and (not isinstance(personal_space, str)
                or not re.fullmatch(r"[0-9a-f]{32}", personal_space)):
            raise ValueError("Invalid personal space")
        # Filter ownership before LIMIT and hydrate only summary fields, not up
        # to hundreds of large saved transcripts from unrelated personal spaces.
        payload = "CASE WHEN m.key LIKE 'meu.sync.backup:%' THEN m.value ELSE '{}' END"
        rows = conn.execute(
            f"""SELECT s.id, substr(s.title, 1, 160) AS title,
                   json_extract(m.value, '$.receipt') AS receipt,
                   json_extract(m.value, '$.created_at') AS created_at,
                   json_extract(m.value, '$.prefer') AS prefer
                FROM state_meta m JOIN sessions s ON s.id = json_extract({payload}, '$.id')
                WHERE m.key LIKE 'meu.sync.backup:%' AND ({db._MEU_SYNC_PROFILE_SCOPE})
                  AND (? IS NULL OR s.id = ?)
                  AND (? IS NULL OR EXISTS (SELECT 1 FROM state_meta owner
                      WHERE owner.key = 'meu.space.session:' || s.id AND owner.value = ?))
                ORDER BY m.rowid DESC LIMIT 20""",
            (session_id, session_id, personal_space, personal_space),
        ).fetchall()
        return {"backups": [{**dict(row), "title": row["title"] or "Συνομιλία"} for row in rows]}
