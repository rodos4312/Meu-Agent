"""Offline continuation recovery is explicit, backed up, atomic and version-bound."""
import os
from copy import deepcopy

import pytest

from hermes_state import SessionDB
from hermes_state_errors import SessionActiveWriteGuardError
from hermes_state_ids import new_session_id
from hermes_state_meu_sync import fingerprint


def _diverge(pc, phone):
    sid = new_session_id()
    pc.create_session(sid, source="gui")
    pc.append_message(sid, "user", "Shared prompt")
    pc.append_message(sid, "assistant", "Shared answer")
    phone.apply_meu_sync_history(pc.export_meu_sync_history(sid), profile_sync=True)
    pc.append_message(sid, "assistant", "PC answer before restart")
    phone.append_message(sid, "user", "Phone work while PC is closed")
    phone.append_message(sid, "assistant", "Phone answer")
    versions = {side: db.export_meu_sync_history(sid, profile_sync=True, timestamps=True)
                for side, db in (("pc", pc), ("phone", phone))}
    return sid, {**versions, "prefer": "phone", "expected": fingerprint(versions["pc"])}


def test_recovery_keeps_both_versions_and_converges_after_pc_restart(tmp_path):
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        sid, request = _diverge(pc, phone)
        assert pc.apply_meu_sync_history(request["phone"], profile_sync=True) == "conflict"
        first = pc.resolve_meu_sync_history(request)
        assert first["status"] == "resolved"
        second = phone.resolve_meu_sync_history({**request, "expected": fingerprint(request["phone"])})
        assert second == first
        assert pc.export_meu_sync_history(sid) == phone.export_meu_sync_history(sid)
        backup = pc.list_meu_sync_backups(session_id=sid, receipt=first["receipt"])
        assert backup["pc"] == request["pc"]
        assert backup["phone"] == request["phone"]
        assert len(pc.list_meu_sync_backups()["backups"]) == 1
        assert any(row["content"] == "PC answer before restart" and not row["active"]
                   for row in pc.get_messages(sid, include_inactive=True))
        # Lost HTTP responses may retry; a later turn must never be overwritten.
        assert pc.resolve_meu_sync_history(request) == first
        phone.append_message(sid, "user", "Another offline message")
        with SessionDB(tmp_path / "pc.db") as restarted:
            assert restarted.apply_meu_sync_history(phone.export_meu_sync_history(sid), profile_sync=True) == "appended"
            assert restarted.resolve_meu_sync_history(request) == {"status": "stale"}
            assert restarted.export_meu_sync_history(sid) == phone.export_meu_sync_history(sid)


def test_new_messages_or_a_live_turn_refuse_recovery_without_writes(tmp_path):
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        sid, request = _diverge(pc, phone)
        holder = f"pid={os.getpid()}:sync-recovery"
        assert pc.try_acquire_session_turn_lease(sid, holder)
        with pytest.raises(SessionActiveWriteGuardError):
            pc.resolve_meu_sync_history(request)
        pc.release_session_turn_lease(sid, holder)
        pc.append_message(sid, "user", "Arrived after the comparison")
        before = pc.export_meu_sync_history(sid)
        assert pc.resolve_meu_sync_history(request) == {"status": "stale"}
        assert pc.list_meu_sync_backups() == {"backups": []}
        assert pc.export_meu_sync_history(sid) == before


def test_failed_rewrite_rolls_back_the_backup_and_transcript(tmp_path, monkeypatch):
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        sid, request = _diverge(pc, phone)
        before = pc.export_meu_sync_history(sid)

        def failed(*args, **kwargs):
            raise RuntimeError("Simulated disk failure")

        monkeypatch.setattr(pc, "replace_messages_in_transaction", failed)
        with pytest.raises(RuntimeError, match="Simulated disk failure"):
            pc.resolve_meu_sync_history(request)
        assert pc.list_meu_sync_backups() == {"backups": []}
        assert pc.export_meu_sync_history(sid) == before


def test_recovery_and_backup_reads_respect_personal_space(tmp_path):
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        sid, request = _diverge(pc, phone)
        space, stranger = "a" * 32, "b" * 32
        pc._execute_write(lambda conn: conn.execute(
            "INSERT INTO state_meta(key,value) VALUES (?,?)", ("meu.space.session:" + sid, space)))
        with pytest.raises(LookupError):
            pc.resolve_meu_sync_history(request, personal_space=stranger)
        result = pc.resolve_meu_sync_history(request, personal_space=space)
        assert pc.list_meu_sync_backups(personal_space=stranger) == {"backups": []}
        with pytest.raises(LookupError):
            pc.list_meu_sync_backups(session_id=sid, receipt=result["receipt"], personal_space=stranger)
        assert pc.list_meu_sync_backups(session_id=sid, receipt=result["receipt"], personal_space=space)["id"] == sid


def test_recovery_preserves_internal_rows_before_the_shared_visible_prefix(tmp_path):
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        sid = new_session_id()
        pc.create_session(sid, source="gui")
        pc.append_message(sid, "system", "Local context")
        pc.append_message(sid, "user", "Shared question")
        pc.append_message(sid, "tool", "Private tool result", tool_call_id="fixture")
        pc.append_message(sid, "assistant", "Shared answer")
        phone.apply_meu_sync_history(pc.export_meu_sync_history(sid), profile_sync=True)
        pc.append_message(sid, "assistant", "PC suffix")
        phone.append_message(sid, "user", "Phone suffix")
        a, b = pc.export_meu_sync_history(sid), phone.export_meu_sync_history(sid)
        result = pc.resolve_meu_sync_history({"pc": a, "phone": b, "prefer": "phone", "expected": fingerprint(a)})
        assert result["status"] == "resolved"
        assert any(row["role"] == "tool" and row["content"] == "Private tool result" for row in pc.get_messages(sid))
        backup = pc.list_meu_sync_backups(session_id=sid, receipt=result["receipt"])
        assert all(row["role"] in ("user", "assistant") for row in backup["local_before"]["messages"])


@pytest.mark.parametrize("malformed", ["tool_calls", "duplicate_identity", "configuration"])
def test_recovery_cannot_import_tools_or_configuration(tmp_path, malformed):
    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        sid, original = _diverge(pc, phone)
        request = deepcopy(original)
        if malformed == "tool_calls":
            request["phone"]["messages"][-1]["tool_calls"] = [{"name": "terminal"}]
        elif malformed == "duplicate_identity":
            request["phone"]["messages"][-1]["message_uid"] = request["phone"]["messages"][0]["message_uid"]
        else:
            request["phone"]["model_config"] = {"provider": "another-provider"}
        before = pc.export_meu_sync_history(sid)
        with pytest.raises(ValueError):
            pc.resolve_meu_sync_history(request)
        assert pc.export_meu_sync_history(sid) == before
        assert pc.list_meu_sync_backups() == {"backups": []}
