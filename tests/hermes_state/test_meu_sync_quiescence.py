"""A phone must never synchronize a reply that its source is still writing."""
import os

import pytest

from hermes_state import SessionDB
from hermes_state_errors import SessionActiveWriteGuardError, SessionTurnLeaseLostError
from hermes_state_ids import new_session_id


def test_sync_defers_export_until_the_source_turn_finishes(tmp_path):
    sid = new_session_id()
    holder = f"pid={os.getpid()}:meu-sync-test"
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        pc.create_session(sid, source="gui")
        pc.append_message(sid, "user", "Continue on the phone while the PC restarts")
        initial = pc.export_meu_sync_history(sid, profile_sync=True)
        assert phone.apply_meu_sync_history(initial, profile_sync=True) == "created"
        assert pc.try_acquire_session_turn_lease(sid, holder)
        pc.append_message(sid, "assistant", "Partial reply")
        with pytest.raises(SessionActiveWriteGuardError):
            pc.export_meu_sync_history(sid, profile_sync=True)
        assert phone.export_meu_sync_history(sid, profile_sync=True) == initial
        pc.release_session_turn_lease(sid, holder)
        settled = pc.export_meu_sync_history(sid, profile_sync=True)
        assert phone.apply_meu_sync_history(settled, profile_sync=True) == "appended"
        phone.append_message(sid, "user", "Offline continuation")
        with SessionDB(tmp_path / "pc.db") as restarted:
            assert restarted.apply_meu_sync_history(
                phone.export_meu_sync_history(sid, profile_sync=True), profile_sync=True,
            ) == "appended"
            assert restarted.export_meu_sync_history(sid) == phone.export_meu_sync_history(sid)


def test_running_destination_is_busy_before_declaring_a_conflict(tmp_path):
    sid = new_session_id()
    holder = f"pid={os.getpid()}:meu-sync-running"
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        pc.create_session(sid, source="gui")
        pc.append_message(sid, "user", "Common prefix")
        phone.apply_meu_sync_history(pc.export_meu_sync_history(sid), profile_sync=True)
        pc.append_message(sid, "assistant", "PC continuation")
        phone.append_message(sid, "assistant", "Phone continuation")
        incoming = phone.export_meu_sync_history(sid)
        assert pc.try_acquire_session_turn_lease(sid, holder)
        with pytest.raises(SessionTurnLeaseLostError):
            pc.apply_meu_sync_history(incoming, profile_sync=True)
        pc.release_session_turn_lease(sid, holder)
        assert pc.apply_meu_sync_history(incoming, profile_sync=True) == "conflict"
        assert pc.export_meu_sync_history(sid)["messages"][-1]["content"] == "PC continuation"


def test_read_only_sync_waits_for_compression_without_changing_the_store(tmp_path):
    path = tmp_path / "state.db"
    sid = new_session_id()
    holder = f"pid={os.getpid()}:meu-sync-compression"
    with SessionDB(path) as writer:
        writer.create_session(sid, source="gui")
        writer.append_message(sid, "user", "Keep this exact history")
        before = writer.export_meu_sync_history(sid)
        assert writer.try_acquire_compression_lock(sid, holder)
        with SessionDB(path, read_only=True) as reader:
            with pytest.raises(SessionActiveWriteGuardError):
                reader.export_meu_sync_history(sid, profile_sync=True)
            writer.release_compression_lock(sid, holder)
            assert reader.export_meu_sync_history(sid, profile_sync=True) == before


def test_queued_work_is_not_exported_as_a_settled_conversation(tmp_path):
    with SessionDB(tmp_path / "state.db") as db:
        sid = new_session_id()
        db.create_session(sid, source="gui")
        db.append_message(sid, "user", "Queued before restart")
        db._execute_write(lambda conn: conn.execute(
            "INSERT INTO session_admissions(admission_id, request_id, principal_id, target_session_id, "
            "lineage_json, payload_json, payload_digest, intent, status) VALUES(?,?,?,?,?,?,?,'queue','queued')",
            ("sync-fixture", "request", "owner", sid, "[]", "{}", "f" * 64)))
        with pytest.raises(SessionActiveWriteGuardError):
            db.export_meu_sync_history(sid, profile_sync=True)
        db._execute_write(lambda conn: conn.execute(
            "UPDATE session_admissions SET status = 'terminal' WHERE admission_id = 'sync-fixture'"))
        assert db.export_meu_sync_history(sid)["messages"][0]["content"] == "Queued before restart"
