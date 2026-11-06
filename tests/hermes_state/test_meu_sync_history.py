"""Two local stores exchanging plain transcript snapshots."""
import pytest

from hermes_state import SessionDB
from hermes_state_ids import new_session_id


def test_sync_appends_in_both_directions_and_retries(tmp_path):
    sid = new_session_id()
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        pc.create_session(sid, source="gui")
        pc.append_message(sid, "user", "Από το PC")
        pc.append_message(sid, "assistant", "Ιδιωτικό", display_kind="hidden")
        history = pc.export_meu_sync_history(sid)
        assert [msg["content"] for msg in history["messages"]] == ["Από το PC"]
        assert phone.apply_meu_sync_history(history) == "created"
        assert phone.apply_meu_sync_history(history) == "unchanged"

        phone.append_message(sid, "assistant", "Από το κινητό")
        extended = phone.export_meu_sync_history(sid)
        assert pc.apply_meu_sync_history(extended) == "appended"
        assert pc.apply_meu_sync_history(extended) == "unchanged"
        assert pc.export_meu_sync_history(sid) == extended


def test_sync_leaves_divergent_histories_intact(tmp_path):
    sid = new_session_id()
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        pc.create_session(sid, source="gui")
        pc.append_message(sid, "user", "Κοινή αρχή")
        phone.apply_meu_sync_history(pc.export_meu_sync_history(sid))
        pc.append_message(sid, "user", "Συνέχεια PC")
        phone.append_message(sid, "user", "Συνέχεια κινητού")
        local = pc.export_meu_sync_history(sid)
        remote = phone.export_meu_sync_history(sid)

        assert pc.apply_meu_sync_history(remote) == "conflict"
        assert phone.apply_meu_sync_history(local) == "conflict"
        assert pc.export_meu_sync_history(sid) == local
        assert phone.export_meu_sync_history(sid) == remote


def test_sync_rejects_tool_calls(tmp_path):
    with SessionDB(tmp_path / "state.db") as db:
        sid = new_session_id()
        with pytest.raises(ValueError, match="visible text only"):
            db.apply_meu_sync_history({
                "id": sid,
                "messages": [{"role": "assistant", "content": "text",
                              "message_uid": "a" * 32, "tool_calls": []}],
            })
        assert db.get_session(sid) is None


def test_sync_catalog_paginates_local_chats_without_exposing_hidden_or_external_rows(tmp_path):
    ids = ["local-" + digit * 64 for digit in "123456"]
    with SessionDB(tmp_path / "state.db") as db:
        db.create_session(ids[0], source="gui")
        db.create_session(ids[1], source="telegram")
        db.create_session(ids[2], source="desktop")
        db.create_session(ids[3], source="gui", parent_session_id=ids[0])
        db.create_session(ids[4], source="gui")
        db.create_session(ids[5], source="gui")
        db._execute_write(lambda conn: conn.execute(
            "UPDATE sessions SET hidden = 1 WHERE id = ?", (ids[4],)))
        db._execute_write(lambda conn: conn.execute(
            "UPDATE sessions SET end_reason = 'compression' WHERE id = ?", (ids[5],)))

        first = db.list_meu_sync_sessions(limit=1)
        assert first == {"ids": [ids[0]], "next": ids[0]}
        db.append_message(ids[0], "user", "Recent activity does not move the cursor")
        assert db.list_meu_sync_sessions(after=first["next"], limit=1) == {
            "ids": [ids[2]], "next": None}
        with pytest.raises(ValueError, match="cursor"):
            db.list_meu_sync_sessions(after="bad cursor")
