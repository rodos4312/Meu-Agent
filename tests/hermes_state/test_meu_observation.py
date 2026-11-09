"""A paired view can move while the canonical source/destination is executing."""
import os

import pytest

from hermes_state import SessionDB
from hermes_state_errors import SessionActiveWriteGuardError
from hermes_state_ids import new_session_id
from hermes_state_meu_observation import display_observation, observe, read_view, remote_view, require_local_execution
from hermes_state_runtime import RuntimeStoreError


def test_live_projection_does_not_change_execution_history_and_settles_without_duplicates(tmp_path):
    sid = new_session_id()
    with SessionDB(tmp_path / 'pc.db') as pc, SessionDB(tmp_path / 'phone.db') as phone:
        pc.create_session(sid, source='gui')
        pc.append_message(sid, 'user', 'Build the app')
        phone.apply_meu_sync_history(pc.export_meu_sync_history(sid), profile_sync=True)
        baseline = phone.get_messages(sid)
        holder = f'pid={os.getpid()}:live-view'
        assert pc.try_acquire_session_turn_lease(sid, holder)
        with pytest.raises(SessionActiveWriteGuardError):
            pc.export_meu_sync_history(sid, profile_sync=True)
        view = read_view(pc, sid)
        assert view['busy'] is True
        view['draft'] = 'Working on the first screen'
        observe(phone, 'pc', view)
        assert phone.get_messages(sid) == baseline
        displayed = display_observation(phone, sid)
        assert displayed['draft'] == view['draft']
        assert displayed['messages'] == []
        with pytest.raises(RuntimeStoreError, match='session_busy'):
            require_local_execution(phone, sid)
        # The display transport can fail/disappear without changing the source lease.
        assert read_view(pc, sid)['busy'] is True
        pc.append_message(sid, 'assistant', 'Finished app')
        pc.release_session_turn_lease(sid, holder)
        observe(phone, 'pc', read_view(pc, sid))
        assert display_observation(phone, sid)['messages'][-1]['content'] == 'Finished app'
        settled = pc.export_meu_sync_history(sid, profile_sync=True)
        assert phone.apply_meu_sync_history(settled, profile_sync=True) == 'appended'
        assert remote_view(phone, sid) is None
        require_local_execution(phone, sid)
        assert display_observation(phone, sid) is None
        assert len(phone.get_messages(sid)) == 2
        # Reverse direction, while the phone owns its own execution.
        assert phone.try_acquire_session_turn_lease(sid, holder)
        view = read_view(phone, sid)
        view['draft'] = 'Now working on the phone'
        observe(pc, 'phone', view)
        assert display_observation(pc, sid)['draft'] == view['draft']
        assert read_view(phone, sid)['messages'] == read_view(pc, sid)['messages']
        phone.release_session_turn_lease(sid, holder)


def test_busy_destination_is_never_replaced_and_divergent_views_are_not_merged(tmp_path):
    sid = new_session_id()
    with SessionDB(tmp_path / 'store.db') as db:
        db.create_session(sid, source='gui')
        db.append_message(sid, 'user', 'Shared prefix')
        baseline = db.get_messages(sid)
        holder = f'pid={os.getpid()}:busy-destination'
        assert db.try_acquire_session_turn_lease(sid, holder)
        view = read_view(db, sid)
        view['draft'] = 'Remote answer'
        observe(db, 'phone', view)
        assert display_observation(db, sid) is None
        db.release_session_turn_lease(sid, holder)
        view['messages'].append({'role': 'assistant', 'content': 'Branch A', 'message_uid': 'a' * 32})
        observe(db, 'phone', view)
        view['messages'][-1] = {'role': 'assistant', 'content': 'Branch B', 'message_uid': 'b' * 32}
        observe(db, 'another-phone', view)
        warning = display_observation(db, sid)
        assert warning['messages'] == []
        assert warning['busy'] is True
        with pytest.raises(RuntimeStoreError, match='session_busy'):
            require_local_execution(db, sid)
        assert db.get_messages(sid) == baseline


def test_expired_view_cannot_keep_a_local_chat_busy(tmp_path, monkeypatch):
    import hermes_state_meu_observation as module
    now = [1000.0]
    monkeypatch.setattr(module.time, 'time', lambda: now[0])
    with SessionDB(tmp_path / 'store.db') as db:
        sid = new_session_id()
        db.create_session(sid, source='gui')
        view = read_view(db, sid)
        view.update(busy=True, draft='Temporary display')
        observe(db, 'pc', view)
        assert remote_view(db, sid) is not None
        now[0] += 91
        assert remote_view(db, sid) is None
        require_local_execution(db, sid)


def test_views_reject_tools_oversized_drafts_and_nonshareable_sessions(tmp_path):
    with SessionDB(tmp_path / 'store.db') as db:
        sid = new_session_id()
        db.create_session(sid, source='gui')
        view = read_view(db, sid)
        for bad in ({**view, 'tool_calls': []}, {**view, 'busy': True, 'draft': 'x' * (256 * 1024 + 1)}):
            with pytest.raises(ValueError):
                observe(db, 'pc', bad)
        db.create_session('outside', source='telegram')
        with pytest.raises((ValueError, LookupError)):
            read_view(db, 'outside')


def test_new_phone_chat_is_discoverable_without_admitting_an_agent_and_keeps_its_space(tmp_path):
    with SessionDB(tmp_path / 'phone.db') as phone, SessionDB(tmp_path / 'pc.db') as pc:
        sid = new_session_id()
        phone.create_session(sid, source='gui')
        phone.append_message(sid, 'user', 'New phone project')
        view = read_view(phone, sid)
        view.update(busy=True, draft='Building the first files')
        observe(pc, 'phone', view, personal_space='a' * 32)
        assert pc.get_session(sid) is not None
        assert read_view(pc, sid)['messages'] == view['messages']
        assert pc.get_meta('meu.space.session:' + sid) == 'a' * 32
        assert pc._read_one('SELECT COUNT(*) FROM session_admissions')[0] == 0
        with pytest.raises(LookupError):
            observe(pc, 'other-phone', view, personal_space='b' * 32)
        assert pc.get_meta('meu.space.session:' + sid) == 'a' * 32
