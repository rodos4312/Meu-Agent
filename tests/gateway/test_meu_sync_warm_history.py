"""Explicit sync recovery must reach warm agents, including equal-length histories."""
import asyncio
from contextlib import contextmanager
import threading
from types import SimpleNamespace

import pytest

from hermes_state import AsyncSessionDB, SessionDB
from hermes_state_ids import new_session_id
from hermes_state_meu_sync import fingerprint


def _recover(pc, phone, extra):
    sid = new_session_id()
    pc.create_session(sid, source="gui")
    pc.append_message(sid, "user", "Shared question")
    pc.append_message(sid, "assistant", "Shared answer")
    phone.apply_meu_sync_history(pc.export_meu_sync_history(sid), profile_sync=True)
    pc.append_message(sid, "user", "PC question")
    pc.append_message(sid, "assistant", "PC answer")
    for index in range(extra):
        phone.append_message(sid, "user" if index % 2 == 0 else "assistant", f"Phone {index}")
    copies = {side: db.export_meu_sync_history(sid, profile_sync=True)
              for side, db in (("pc", pc), ("phone", phone))}
    return sid, {**copies, "prefer": "phone", "expected": fingerprint(copies["pc"])}


@pytest.mark.parametrize("extra", [0, 1, 2, 4])
@pytest.mark.parametrize("stamped", [True, False])
def test_warm_desktop_turn_replaces_displaced_history(tmp_path, monkeypatch, extra, stamped):
    from tui_gateway import server

    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        sid, request = _recover(pc, phone, extra)
        old = pc.get_messages_as_conversation(sid, include_row_ids=stamped)
        session = {"session_key": sid, "history": old, "history_lock": threading.Lock(), "history_version": 0}

        @contextmanager
        def owner_db(record):
            yield pc

        monkeypatch.setattr(server, "_session_db", owner_db)
        assert pc.resolve_meu_sync_history(request)["status"] == "resolved"
        own = pc.append_message(sid, "user", "Next prompt after recovery")
        session["_submit_user_row"] = {"_row_id": own}
        server._adopt_out_of_band_turns(session)
        text = [message["content"] for message in session["history"]]
        assert text == [message["content"] for message in request["phone"]["messages"]]
        assert "PC answer" not in text and "Next prompt after recovery" not in text
        server._adopt_out_of_band_turns(session)
        assert session["history_version"] == 1


def test_equal_length_recovery_evicts_gateway_cache_and_rebaselines(tmp_path):
    from gateway.run import GatewayRunner
    from gateway.session_execution import GatewaySessionAgentMixin

    with SessionDB(tmp_path / "pc.db") as pc, SessionDB(tmp_path / "phone.db") as phone:
        sid, request = _recover(pc, phone, 2)
        runner = GatewayRunner.__new__(GatewayRunner)
        runner._session_db = AsyncSessionDB(pc)
        runner._agent_cache_lock = threading.Lock()
        runner._agent_cache = {}
        runner._init_cached_agent_for_turn = lambda *args: None
        execution = GatewaySessionAgentMixin()
        execution._runner = runner
        execution._ctx = SimpleNamespace(session_id=sid, session_key=sid, _interrupt_depth=0)
        old_count = execution._current_message_count()
        agent = SimpleNamespace(max_iterations=10)
        runner._agent_cache[sid] = (agent, "sig", old_count, sid)
        assert pc.resolve_meu_sync_history(request)["status"] == "resolved"
        current = execution._current_message_count()
        assert isinstance(old_count, int) and current[0] == old_count
        asyncio.run(runner._refresh_agent_cache_message_count(sid, sid))
        assert runner._agent_cache[sid][2] == old_count
        found = execution._lookup_cached_agent("sig", runner._agent_cache_lock,
            runner._agent_cache, 10, sid, False, current)
        assert not found.reused and found.evicted is agent
        runner._agent_cache[sid] = (agent, "sig", current, sid)
        pc.append_message(sid, "user", "Next turn")
        asyncio.run(runner._refresh_agent_cache_message_count(sid, sid))
        found = execution._lookup_cached_agent("sig", runner._agent_cache_lock,
            runner._agent_cache, 10, sid, False, execution._current_message_count())
        assert found.reused and found.agent is agent
