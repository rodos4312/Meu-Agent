"""Chats created from a paired phone carry a stored, never-overwritten origin."""
import json
from types import SimpleNamespace

from gateway.mobile_live import LiveScope
from gateway.mobile_preview import MobilePreview
from gateway.mobile_spaces import PersonalDevices
from hermes_state import SessionDB
from hermes_state_ids import new_session_id


def _history(sid, text='from the phone'):
    return {'id': sid, 'messages': [{'role': 'user', 'content': text, 'message_uid': 'a' * 32}]}


def _origin(db, sid):
    raw = db.get_meta('meu.origin.session:' + sid)
    return json.loads(raw) if raw else None


def test_phone_import_writes_origin_once_and_never_overwrites(tmp_path):
    sid = new_session_id()
    with SessionDB(tmp_path / 'state.db') as db:
        phone = {'kind': 'phone', 'device': 'Κινητό 1'}
        assert db.apply_meu_sync_history(_history(sid), origin=phone) == 'created'
        assert _origin(db, sid) == phone
        longer = _history(sid)
        longer['messages'].append({'role': 'assistant', 'content': 'reply', 'message_uid': 'b' * 32})
        assert db.apply_meu_sync_history(longer, origin={'kind': 'phone', 'device': 'Other'}) == 'appended'
        assert _origin(db, sid) == phone


def test_import_without_origin_leaves_chat_unmarked(tmp_path):
    sid = new_session_id()
    with SessionDB(tmp_path / 'state.db') as db:
        db.apply_meu_sync_history(_history(sid))
        assert _origin(db, sid) is None


def test_live_phone_create_writes_origin_for_owner_space(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        authority = SimpleNamespace(db=db, profile_id=str(tmp_path))
        service = PersonalDevices(db)
        device, space = service.add_owner(authority, name='Owner', label='Κινητό Λάζαρου')
        assert space['owner'] is True
        fake = SimpleNamespace(authority=authority, personal_devices=service, device_id=device['id'])
        preview = SimpleNamespace(authority=authority, personal_space=None,
                                  origin=MobilePreview._phone_origin(fake))
        sid = new_session_id()
        db.create_session(sid, source='gui')
        LiveScope(preview).mark_created({'session_id': sid})
        assert _origin(db, sid) == {'kind': 'phone', 'device': 'Κινητό Λάζαρου'}
        preview.origin = {'kind': 'phone', 'device': 'Changed'}
        LiveScope(preview).mark_created({'session_id': sid})
        assert _origin(db, sid)['device'] == 'Κινητό Λάζαρου'


def test_list_returns_origin_only_for_marked_chats(tmp_path):
    marked, plain = new_session_id(), new_session_id()
    with SessionDB(tmp_path / 'state.db') as db:
        db.apply_meu_sync_history(_history(marked), origin={'kind': 'phone', 'device': 'P'})
        db.create_session(plain, source='gui')
        db.append_message(plain, 'user', 'on the pc')
        rows = {row['id']: row for row in db.list_sessions_rich(limit=10, compact_rows=True)}
        assert rows[marked]['origin'] == {'kind': 'phone', 'device': 'P'}
        assert 'origin' not in rows[plain]
