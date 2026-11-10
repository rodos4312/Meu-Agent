"""A project moves with the user, with no second writer during a partition."""
import base64
import os
from pathlib import Path

import pytest

from hermes_state import SessionDB
from hermes_state_ids import new_session_id
from hermes_state_meu_projects import ProjectStore, require_project_execution
from hermes_state_runtime import RuntimeStoreError
from meu_project_files import CHUNK, manifest, portable


def copy_offer(source, target, offer, root):
    target.receive(offer, root)
    for entry in offer['files']:
        for offset in range(0, max(1, entry['size']), CHUNK):
            chunk = source.chunk(offer['id'], offer['transfer'], entry['path'], offset)
            target.put_chunk(offer['id'], offer['transfer'], entry['path'], offset, chunk['data'])
    assert target.verify(offer['id'], offer['transfer'])['digest'] == offer['digest']


def allowed(db, sid):
    with db._read_ctx() as conn:
        require_project_execution(db, conn, sid)


def test_roundtrip_with_pc_closed_preserves_binary_updates_and_deletes(tmp_path):
    pc_root, phone_root = tmp_path / 'pc-files', tmp_path / 'phone-files'
    pc_root.mkdir(); phone_root.mkdir()
    (pc_root / 'game.js').write_text('level one', encoding='utf8')
    (pc_root / 'empty-assets').mkdir()
    (pc_root / 'icon.png').write_bytes(bytes(range(256)) * 2000)
    (pc_root / '.env').write_text('PRIVATE KEY MUST STAY LOCAL')
    (pc_root / 'node_modules').mkdir()
    (pc_root / 'node_modules' / 'ignored').write_text('cache')
    sid = new_session_id()
    pc_path, phone_path = tmp_path / 'pc-state' / 'pc.db', tmp_path / 'phone-state' / 'phone.db'
    with SessionDB(pc_path) as pc, SessionDB(phone_path) as phone:
        for db in (pc, phone):
            db.create_session(sid, source='gui')
        a, b = ProjectStore(pc), ProjectStore(phone, 'phone-one')
        pid = a.register(pc_root, 'Game', [sid])['id']
        offer = a.prepare(pid, 'phone-one', 'first')
        assert all(item['path'] not in {'.env', 'node_modules/ignored'} for item in offer['files'])
        with pytest.raises(RuntimeStoreError):
            allowed(pc, sid)
        copy_offer(a, b, offer, phone_root)
        with pytest.raises(RuntimeStoreError):
            allowed(phone, sid)
        grant = a.release(pid, 'first')
        assert a.request_return(pid)['return_requested'] is True
        assert a.release(pid, 'first') == grant  # lost HTTP response
        b.activate(grant)
        assert (phone_root / 'empty-assets').is_dir()
        assert b.activate(grant)['phase'] == 'ready'  # lost activation reply
        allowed(phone, sid)
    # Both stores and source runtime closed: reopen only the autonomous phone.
    with SessionDB(phone_path) as phone:
        b = ProjectStore(phone, 'phone-one')
        allowed(phone, sid)
        (phone_root / 'game.js').write_text('level two built offline', encoding='utf8')
        (phone_root / 'icon.png').unlink()
        (phone_root / 'result.apk').write_bytes(b'APK\x00\xff')
        returned = b.prepare(pid, 'pc', 'return')
        with SessionDB(pc_path) as pc:
            a = ProjectStore(pc)
            with pytest.raises(RuntimeStoreError):
                allowed(pc, sid)
            copy_offer(b, a, returned, pc_root)
            a.activate(b.release(pid, 'return'))
            assert a.catalog()['projects'][0]['return_requested'] is False
            allowed(pc, sid)
            assert (pc_root / 'game.js').read_text() == 'level two built offline'
            assert not (pc_root / 'icon.png').exists()
            assert (pc_root / 'result.apk').read_bytes() == b'APK\x00\xff'
            assert (pc_root / '.env').read_text() == 'PRIVATE KEY MUST STAY LOCAL'
            backups = list(tmp_path.glob('.meu-backup-*'))
            assert any((item / 'game.js').read_text() == 'level one' for item in backups if (item / 'game.js').exists())
            with pytest.raises(RuntimeStoreError):
                allowed(phone, sid)


def test_partial_transfer_busy_turn_stale_offer_and_local_edits_never_overwrite(tmp_path):
    root, replica = tmp_path / 'work', tmp_path / 'replica'
    root.mkdir(); replica.mkdir()
    (root / 'file.txt').write_text('original')
    sid = new_session_id()
    with SessionDB(tmp_path / 'a-state' / 'a.db') as a, SessionDB(tmp_path / 'b-state' / 'b.db') as b:
        for db in (a, b):
            db.create_session(sid, source='gui')
        source, target = ProjectStore(a), ProjectStore(b, 'phone-one')
        pid = source.register(root, 'Work', [sid])['id']
        holder = f'pid={os.getpid()}:test'
        assert a.try_acquire_session_turn_lease(sid, holder)
        with pytest.raises(Exception, match='written'):
            source.prepare(pid, 'phone-one', 'busy')
        a.release_session_turn_lease(sid, holder)
        offer = source.prepare(pid, 'phone-one', 'transfer')
        target.receive(offer, replica)
        with pytest.raises(ValueError, match='incomplete_project'):
            target.verify(pid, 'transfer')
        with pytest.raises(ValueError):
            target.activate({'id': pid})
        assert not (replica / 'file.txt').exists()
        copy_offer(source, target, offer, replica)
        grant = source.release(pid, 'transfer')
        target.activate(grant)
        with pytest.raises(ValueError):
            source.prepare(pid, 'another-phone', 'steal')
        (root / 'file.txt').write_text('external edit on inactive PC')
        offer2 = target.prepare(pid, 'pc', 'return')
        with pytest.raises(ValueError, match='local_project_changes'):
            source.receive(offer2, root)
        assert (root / 'file.txt').read_text() == 'external edit on inactive PC'


@pytest.mark.parametrize('path', ['../secret', '/root/a', 'C:/file', 'a\\b', 'A/.env', 'a/CON.txt', 'a/private.key'])
def test_nonportable_or_secret_paths_refused(path):
    with pytest.raises(ValueError):
        portable(path)


def test_personal_space_and_manifest_limits(tmp_path):
    from meu_project_files import validate
    with pytest.raises(ValueError):
        validate([{'path': 'a', 'size': 2**50, 'sha256': 'a' * 64, 'executable': False}])
    root = tmp_path / 'files'; root.mkdir()
    sid = new_session_id()
    with SessionDB(tmp_path / 'state' / 'store.db') as db:
        db.create_session(sid, source='gui')
        store = ProjectStore(db)
        pid = store.register(root, 'Work', [sid])['id']
        assert ProjectStore(db, space='other-person').catalog() == {'projects': []}
        with db._read_ctx() as conn, pytest.raises(LookupError):
            ProjectStore(db, space='other-person')._get(conn, pid)


def test_one_project_cannot_start_a_second_chat_and_activation_recovers_after_rename(tmp_path, monkeypatch):
    root, replica = tmp_path / 'root', tmp_path / 'replica'
    root.mkdir(); replica.mkdir()
    (root / 'main.txt').write_text('verified')
    sid, other = new_session_id(), new_session_id()
    with SessionDB(tmp_path / 'pc-state' / 'store.db') as pc, SessionDB(tmp_path / 'phone-state' / 'store.db') as phone:
        for db in (pc, phone):
            db.create_session(sid, source='gui')
        pc.create_session(other, source='gui', cwd=str(root))
        a, b = ProjectStore(pc), ProjectStore(phone, 'phone')
        pid = a.register(root, 'Work', [sid])['id']
        holder = f'pid={os.getpid()}:other-chat'
        assert pc.try_acquire_session_turn_lease(other, holder)
        with pytest.raises(RuntimeStoreError, match='session_busy'):
            allowed(pc, sid)
        pc.release_session_turn_lease(other, holder)
        offer = a.prepare(pid, 'phone', 'crash')
        copy_offer(a, b, offer, replica)
        grant = a.release(pid, 'crash')
        rename = Path.rename
        def interrupted(path, target):
            if path.name.startswith('.meu-in-'):
                raise OSError('simulated interruption after backup')
            return rename(path, target)
        with monkeypatch.context() as patcher:
            patcher.setattr(Path, 'rename', interrupted)
            with pytest.raises(OSError):
                b.activate(grant)
        with pytest.raises(RuntimeStoreError):
            allowed(phone, sid)
        b.activate(grant)
        allowed(phone, sid)
        assert (replica / 'main.txt').read_text() == 'verified'


def test_receiver_executes_in_its_local_workspace_without_changing_provider(tmp_path):
    from gateway.session_policy import build_policy, policy_scope
    from hermes_state_meu_projects import execution_policy
    from agent.runtime_cwd import resolve_agent_cwd
    root, original = tmp_path / 'Game', tmp_path / 'old'
    root.mkdir(); original.mkdir()
    sid = new_session_id()
    policy = build_policy({'source': 'gui', 'cwd': str(original), 'model': 'selected-model'}, {})
    with SessionDB(tmp_path / 'state' / 'state.db') as db:
        db.create_session(sid, source='gui')
        ProjectStore(db, 'phone').register(root, 'Game', [sid])
        effective = execution_policy(db, sid, policy)
        assert effective.model == policy.model
        assert effective.toolsets == policy.toolsets
        with policy_scope(effective):
            assert Path(resolve_agent_cwd()) == root


def test_cancellation_before_release_can_be_retried_without_a_second_owner(tmp_path):
    root, replica = tmp_path / 'root', tmp_path / 'replica'
    root.mkdir(); replica.mkdir()
    sid = new_session_id()
    with SessionDB(tmp_path / 'pc-state' / 'store.db') as pc, SessionDB(tmp_path / 'phone-state' / 'store.db') as phone:
        for db in (pc, phone):
            db.create_session(sid, source='gui')
        a, b = ProjectStore(pc), ProjectStore(phone, 'phone')
        pid = a.register(root, 'Work', [sid])['id']
        offer = a.prepare(pid, 'phone', 'cancelled')
        b.receive(offer, replica)
        a.cancel_offer(pid, 'cancelled')
        a.cancel_offer(pid, 'cancelled')
        b.discard_receive(pid, 'cancelled')
        allowed(pc, sid)
        with pytest.raises(RuntimeStoreError):
            allowed(phone, sid)
        with pytest.raises(ValueError, match='transfer_cancelled'):
            a.prepare(pid, 'phone', 'cancelled')
        offer = a.prepare(pid, 'phone', 'next')
        copy_offer(a, b, offer, replica)
        grant = a.release(pid, 'next')
        with pytest.raises(ValueError, match='already_released'):
            a.cancel_offer(pid, 'next')
        b.activate(grant)
        allowed(phone, sid)


def test_compressed_continuation_with_old_device_path_blocks_handoff(tmp_path):
    from hermes_state_errors import SessionActiveWriteGuardError
    root = tmp_path / 'local-project'; root.mkdir()
    sid, child = new_session_id(), new_session_id()
    with SessionDB(tmp_path / 'phone-state' / 'store.db') as db:
        db.create_session(sid, source='gui')
        store = ProjectStore(db, 'phone')
        pid = store.register(root, 'Work', [sid])['id']
        db.end_session(sid, 'compression')
        db.create_session(child, source='gui', parent_session_id=sid, cwd=str(tmp_path / 'old-device-path'))
        db._execute_write(lambda conn: conn.execute(
            "INSERT INTO session_admissions(admission_id, request_id, principal_id, target_session_id, "
            "lineage_json, payload_json, payload_digest, intent, status) VALUES(?,?,?,?,?,?,?,'queue','unknown')",
            ('child-work', 'request', 'owner', child, '[]', '{}', 'f' * 64)))
        with pytest.raises(SessionActiveWriteGuardError):
            store.prepare(pid, 'pc', 'compressed-work')
        assert store.catalog()['projects'][0]['phase'] == 'ready'
        db._execute_write(lambda conn: conn.execute(
            "UPDATE session_admissions SET status='terminal' WHERE admission_id='child-work'"))
        assert store.prepare(pid, 'pc', 'settled')['receiver'] == 'pc'


@pytest.mark.platforms('posix')
def test_symlink_is_not_a_project_file(tmp_path):
    root = tmp_path / 'root'; root.mkdir()
    (tmp_path / 'private').write_text('secret')
    (root / 'linked').symlink_to(tmp_path / 'private')
    with pytest.raises(ValueError, match='link_refused'):
        manifest(root)
