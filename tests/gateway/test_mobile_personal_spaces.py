"""Names create private child folders; devices retain independent pinned credentials."""
import asyncio
import base64
import ipaddress
import json
import ssl
from types import SimpleNamespace

from aiohttp import ClientSession
from fastapi import HTTPException
import pytest

from gateway.mobile_preview import MobilePreview
from gateway.mobile_spaces import PersonalDevices
from hermes_cli.meu_transfers import TransferFolder
from hermes_cli.meu_transfer_spaces import SpaceTransferFolder
from hermes_state import SessionDB


@pytest.fixture
def personal(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        authority = SimpleNamespace(db=db, profile_id='fixture-profile', retiring=False, retired=False)
        root = tmp_path / 'kinito'
        root.mkdir()
        TransferFolder(authority).select(str(root))
        yield authority, PersonalDevices(db), root


def test_name_is_folder_and_replacement_device_keeps_personal_data(personal):
    authority, service, root = personal
    first, space = service.add(authority, name='Λάζαρος', label='Κινητό')
    assert (root / 'Λάζαρος').is_dir()
    scoped = SpaceTransferFolder(authority, service, first['id'])
    overview = scoped.listing()
    assert overview['folder'] == 'Λάζαρος' and overview['path'] == ''
    writer = scoped.upload('έργο.txt', overview['root_id'])
    try:
        writer.write(b'project')
        writer.finish()
    finally:
        writer.close()
    second, same = service.add(authority, space_id=space['id'], label='Νέο κινητό')
    service.revoke(authority.profile_id, first['id'])
    with pytest.raises(HTTPException, match='disconnected'):
        scoped.listing()
    fresh = SpaceTransferFolder(authority, PersonalDevices(authority.db), second['id'])
    assert fresh.listing()['files'][0]['name'] == 'έργο.txt'
    assert same == space and (root / 'Λάζαρος' / 'έργο.txt').read_bytes() == b'project'
    assert len(service.public(authority.profile_id)['devices']) == 1


@pytest.mark.parametrize('name', ['../other', '.', 'CON', 'auth.json', 'a/b', 'a\\b', 'a\u202eb', ''])
def test_invalid_name_never_creates_a_folder(personal, name):
    authority, service, root = personal
    with pytest.raises(HTTPException):
        service.add(authority, name=name)
    assert list(root.iterdir()) == []


def test_collisions_profiles_and_root_changes_fail_without_adopting_files(personal, tmp_path):
    authority, service, root = personal
    (root / 'Existing').mkdir()
    (root / 'Existing' / 'private.txt').write_bytes(b'owner')
    with pytest.raises(HTTPException):
        service.add(authority, name='Existing')
    first, _ = service.add(authority, name='User')
    with pytest.raises(HTTPException):
        service.add(authority, name='user')
    other = SimpleNamespace(db=authority.db, profile_id='another-profile')
    assert service.public(other.profile_id) == {'spaces': [], 'devices': []}
    with pytest.raises(HTTPException):
        service.scope(other.profile_id, first['id'])
    replacement = tmp_path / 'replacement'
    replacement.mkdir()
    TransferFolder(authority).select(str(replacement))
    with pytest.raises(HTTPException):
        SpaceTransferFolder(authority, service, first['id']).listing()
    assert list(replacement.iterdir()) == []
    assert (root / 'Existing' / 'private.txt').read_bytes() == b'owner'


def test_transfers_cannot_list_a_neighbour_and_revoke_invalidates_open_upload(personal):
    authority, service, root = personal
    a, _ = service.add(authority, name='Α')
    service.add(authority, name='Β')
    (root / 'Β' / 'private.txt').write_bytes(b'B')
    folder = SpaceTransferFolder(authority, service, a['id'])
    current = folder.listing()
    assert current['files'] == [] and current['folders'] == []
    for path in ('../Β', '/Β', 'Β', '..'):
        with pytest.raises(HTTPException):
            folder.listing(path, current['root_id'])
    writer = folder.upload('partial.txt', current['root_id'])
    try:
        writer.write(b'first')
        service.revoke(authority.profile_id, a['id'])
        with pytest.raises(HTTPException):
            writer.write(b'next')
    finally:
        writer.close()
    assert list((root / 'Α').iterdir()) == []


def test_reselecting_same_root_keeps_names_but_invalidates_old_transfer_tokens(personal):
    authority, service, root = personal
    device, _ = service.add(authority, name='Λάζαρος')
    folder = SpaceTransferFolder(authority, service, device['id'])
    previous = folder.listing()['root_id']
    TransferFolder(authority).select('')
    with pytest.raises(HTTPException):
        folder.grant(previous)
    TransferFolder(authority).select(str(root))
    assert folder.listing()['folder'] == 'Λάζαρος'
    with pytest.raises(HTTPException):
        folder.upload('stale.txt', previous)


def test_sync_ownership_is_atomic_and_catalogs_do_not_leak_titles_or_fingerprints(personal):
    authority, service, _ = personal
    db = authority.db
    _, a = service.add(authority, name='Α')
    _, b = service.add(authority, name='Β')
    ids = ['local-' + char * 64 for char in 'abc']
    for sid, space in zip(ids, (a, b, a)):
        history = {'id': sid, 'messages': [{'role': 'user', 'content': 'private', 'message_uid': sid[-32:]}]}
        assert db.apply_meu_sync_history(history, profile_sync=True, personal_space=space['id']) == 'created'
    first = db.list_meu_sync_sessions(personal_space=a['id'], limit=1, fingerprints=True)
    assert first['ids'] == [ids[0]] and set(first['fingerprints']) == {ids[0]}
    second = db.list_meu_sync_sessions(personal_space=a['id'], after=first['next'], fingerprints=True)
    assert second['ids'] == [ids[2]]
    for key in ('titles', 'fingerprints'):
        assert ids[1] not in first[key] and ids[1] not in second[key]
    owner_sid = 'local-' + 'd' * 64
    db.create_session(owner_sid, source='gui')
    owner = db.export_meu_sync_history(owner_sid, profile_sync=True)
    with pytest.raises(LookupError):
        db.apply_meu_sync_history(owner, profile_sync=True, personal_space=a['id'])
    for space in (a, b):
        assert owner_sid not in db.list_meu_sync_sessions(personal_space=space['id'])['ids']


def test_device_administration_requires_the_native_pc_owner(personal, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers import mobile_preview as routes
    from hermes_cli.web_routers.webapp_access import owner_on_this_machine

    authority, service, _ = personal
    app = FastAPI()
    app.include_router(routes.router)
    state = SimpleNamespace(session_authority=authority, personal_devices=service)
    monkeypatch.setattr(routes, '_scope', lambda request: (state, authority))
    with TestClient(app) as client:
        assert client.get('/api/mobile-preview/devices').status_code == 403
        assert client.post('/api/mobile-preview/devices', json={'name': 'Forbidden'}).status_code == 403
        device, _ = service.add(authority, name='Λάζαρος')
        assert client.delete('/api/mobile-preview/devices/' + device['id']).status_code == 403
        app.dependency_overrides[owner_on_this_machine] = lambda: None
        public = client.get('/api/mobile-preview/devices').json()
        assert public['spaces'][0]['name'] == 'Λάζαρος'
        assert client.delete('/api/mobile-preview/devices/' + device['id']).status_code == 200
        assert service.public(authority.profile_id)['devices'] == []


def test_two_spaces_pair_transfer_sync_revoke_and_restore_with_real_tls(personal):
    asyncio.run(_paired_spaces(*personal))


async def _paired_spaces(authority, service, root):
    previews = []
    credentials = []
    try:
        async with ClientSession() as client:
            for name in ('Λάζαρος', 'Μαρία'):
                device, space = service.add(authority, name=name)
                preview = MobilePreview(authority, ipaddress.IPv4Interface('127.0.0.1/8'),
                                        sync_profile=True, pairing_store=authority.db,
                                        personal_devices=service, device_id=device['id'])
                previews.append(preview)
                await preview.start()
                _, *fields = preview.code.split('.')
                origin, challenge, cert = [base64.urlsafe_b64decode(f + '=' * (-len(f) % 4)) for f in fields]
                origin = origin.decode()
                tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
                async with client.post(origin + '/meu/pair', ssl=tls, json={'challenge': challenge.decode()}) as response:
                    assert response.status == 200
                    body = await response.json()
                assert body['space_name'] == name
                headers = {'Authorization': 'Bearer ' + body['key']}
                credentials.append((origin, tls, headers, device, space))
                async with client.post(origin + '/meu/pair', ssl=tls, json={'challenge': challenge.decode()}) as response:
                    assert response.status == 401
            a, b = credentials
            async with client.get(b[0] + '/api/meu-transfers', ssl=b[1], headers=a[2]) as response:
                assert response.status == 401
            for index, (origin, tls, headers, _, _) in enumerate(credentials):
                async with client.get(origin + '/api/meu-transfers', ssl=tls, headers=headers) as response:
                    listing = await response.json()
                async with client.post(origin + '/api/meu-transfers/upload', ssl=tls, headers=headers,
                                       params={'name': 'same.txt', 'root_id': listing['root_id']},
                                       data=str(index).encode()) as response:
                    assert response.status == 200
                assert (root / ('Λάζαρος', 'Μαρία')[index] / 'same.txt').read_bytes() == str(index).encode()
            sid = 'local-' + 'a' * 64
            history = {'id': sid, 'messages': [{'role': 'user', 'content': 'Private', 'message_uid': '1' * 32}]}
            async with client.put(a[0] + '/meu/sync/sessions/' + sid, ssl=a[1], headers=a[2], json=history) as response:
                assert response.status == 200
            async with client.get(b[0] + '/meu/sync/sessions?fingerprints=1', ssl=b[1], headers=b[2]) as response:
                assert await response.json() == {'ids': [], 'next': None, 'titles': {}, 'fingerprints': {}}
            for method in ('GET', 'PUT'):
                async with client.request(method, b[0] + '/meu/sync/sessions/' + sid, ssl=b[1], headers=b[2],
                                          **({'json': history} if method == 'PUT' else {})) as response:
                    assert response.status == 404
            # The PC owner continues to see all imported text using its normal store.
            assert authority.db.export_meu_sync_history(sid)['messages'] == history['messages']
            saved = next(d for d in service.saved() if d['id'] == a[3]['id'])['pairing']
            public = json.dumps(service.public(authority.profile_id))
            assert a[2]['Authorization'][7:] not in public and saved['digest'] not in public and 'PRIVATE KEY' not in public
            await previews[0].close()
            restored = MobilePreview(authority, ipaddress.IPv4Interface('127.0.0.1/8'), sync_profile=True,
                                     pairing_store=authority.db, personal_devices=PersonalDevices(authority.db), device_id=a[3]['id'])
            previews.append(restored)
            await restored.start(saved=saved)
            async with client.get(a[0] + '/meu/sync/sessions', ssl=a[1], headers=a[2]) as response:
                assert (await response.json())['ids'] == [sid]
            service.revoke(authority.profile_id, a[3]['id'])
            async with client.get(a[0] + '/api/meu-transfers', ssl=a[1], headers=a[2]) as response:
                assert response.status == 410
            async with client.get(b[0] + '/api/meu-transfers', ssl=b[1], headers=b[2]) as response:
                assert response.status == 200
    finally:
        for preview in previews:
            await preview.close()
