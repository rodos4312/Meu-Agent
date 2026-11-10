"""Cancellation before a replica receives an offer must not strand the phone journal."""
import pytest

from hermes_state import SessionDB
from hermes_state_ids import new_session_id
from hermes_state_meu_projects import ProjectStore, require_project_execution
from hermes_state_runtime import RuntimeStoreError


def _copy(source, target, offer, root):
    target.receive(offer, root)
    for entry in offer['files']:
        chunk = source.chunk(offer['id'], offer['transfer'], entry['path'], 0)
        target.put_chunk(offer['id'], offer['transfer'], entry['path'], 0, chunk['data'])
    assert target.verify(offer['id'], offer['transfer'])['digest'] == offer['digest']


def _allowed(db, sid):
    with db._read_ctx() as conn:
        require_project_execution(db, conn, sid)


@pytest.mark.parametrize('replica_phase', ['ready', 'released'])
def test_cancel_before_receive_keeps_owner_and_allows_the_next_handoff(tmp_path, replica_phase):
    pc_root, phone_root = tmp_path / 'pc-project', tmp_path / 'phone-project'
    pc_root.mkdir(); phone_root.mkdir()
    (pc_root / 'main.txt').write_text('original', encoding='utf8')
    sid = new_session_id()
    with SessionDB(tmp_path / 'pc-state' / 'state.db') as pc, SessionDB(tmp_path / 'phone-state' / 'state.db') as phone:
        for db in (pc, phone):
            db.create_session(sid, source='gui')
        a, b = ProjectStore(pc), ProjectStore(phone, 'phone')
        pid = a.register(pc_root, 'Work', [sid])['id']
        if replica_phase == 'released':
            first = a.prepare(pid, 'phone', 'first')
            _copy(a, b, first, phone_root)
            b.activate(a.release(pid, 'first'))
            source, target, owner_db, other_db, root = b, a, phone, pc, pc_root
        else:
            b.register(phone_root, 'Work', [sid], pid=pid, owner='pc')
            source, target, owner_db, other_db, root = a, b, pc, phone, phone_root
        source.prepare(pid, target.local, 'interrupted')
        # Simulate losing the connection before receive reaches the other device.
        source.cancel_offer(pid, 'interrupted')
        target.discard_receive(pid, 'interrupted')
        target.discard_receive(pid, 'interrupted')
        _allowed(owner_db, sid)
        with pytest.raises(RuntimeStoreError):
            _allowed(other_db, sid)
        assert (pc_root / 'main.txt').read_text(encoding='utf8') == 'original'
        next_offer = source.prepare(pid, target.local, 'retry')
        _copy(source, target, next_offer, root)
        # A delayed old cancellation must not discard this newer incoming offer.
        with pytest.raises(ValueError, match='handoff_mismatch'):
            target.discard_receive(pid, 'interrupted')
        target.activate(source.release(pid, 'retry'))
        _allowed(other_db, sid)
        with pytest.raises(RuntimeStoreError):
            _allowed(owner_db, sid)
        assert (root / 'main.txt').read_text(encoding='utf8') == 'original'
