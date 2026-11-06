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
