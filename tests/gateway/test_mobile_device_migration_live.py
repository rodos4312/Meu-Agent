"""The old phone keeps its pinned credential through enrolment and owner restart."""
import base64
import json
from pathlib import Path
import ssl

import httpx

from hermes_state import SessionDB
from tests.gateway.fixtures.local_recovery_probe import child_env, daemon
from tests.gateway.test_native_http_auth import headers, ticket
from tests.waiting import wait_until


def pair(client, code):
    version, *fields = code.split('.')
    assert version == 'meusync2'
    origins, challenge, certificate = [base64.urlsafe_b64decode(field + '=' * (-len(field) % 4)) for field in fields]
    origin = origins.decode().splitlines()[0]
    tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(certificate))
    phone = httpx.Client(base_url=origin, verify=tls, trust_env=False, timeout=15)
    response = phone.post('/meu/pair', json={'challenge': challenge.decode()})
    assert response.status_code == 200, response.text
    phone.headers['Authorization'] = 'Bearer ' + response.json()['key']
    client.append(phone)
    return phone


def test_migration_preserves_real_tls_history_and_files_after_restart(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home, user, shared = tmp_path / 'home', tmp_path / 'user', tmp_path / 'shared'
    for folder in (home, user, shared):
        folder.mkdir()
    (shared / 'existing.txt').write_bytes('Αρχικό έργο'.encode())
    sid = 'local-' + 'a' * 64
    history = {'id': sid, 'messages': [{'role': 'user', 'content': 'existing chat', 'message_uid': 'b' * 32}]}
    with SessionDB(home / 'state.db') as db:
        db.apply_meu_sync_history(history, profile_sync=True)
    (home / 'config.yaml').write_text(json.dumps({
        'model': {'provider': 'custom', 'default': 'fixture', 'base_url': 'http://127.0.0.1:1/v1'},
        'gateway': {'multiplex_profiles': False}, 'auxiliary': {'title_generation': {'enabled': False}},
    }))
    env = child_env()
    env.update(HOME=str(user), USERPROFILE=str(user), HERMES_HOME=str(home), PYTHONPATH=str(root),
               OPENAI_API_KEY='fixture-only', PYTHONUNBUFFERED='1')
    phones = []
    try:
        with daemon(root, home, env, barrier=True, fixture='mobile_devices_daemon.py') as (_, desc):
            with httpx.Client(base_url=desc['api_origin'], trust_env=False, timeout=30) as pc:
                assert pc.post('/api/meu-transfers/folder', headers=headers(ticket(home, desc)),
                               json={'directory': str(shared)}).status_code == 200
                legacy = pc.post('/api/mobile-preview/sync/profile', headers=headers(ticket(home, desc)))
                assert legacy.status_code == 200, legacy.text
                first = pair(phones, legacy.json()['code'])
                generation = first.get('/meu/transfers').json()['root_id']
                previous = first.get('/meu/sync/sessions/' + sid).json()
                adopted = pc.post('/api/mobile-preview/devices/migrate', headers=headers(ticket(home, desc)),
                                  json={'name': 'Λάζαρος', 'label': 'Old phone'})
                assert adopted.status_code == 200, (adopted.text, (home / 'first.log').read_text())
                device_id = adopted.json()['device_id']
                public = pc.get('/api/mobile-preview/devices', headers=headers(ticket(home, desc))).json()
                assert public['legacy'] is None
                space = next(space for space in public['spaces'] if space['owner'])
                assert len(public['devices']) == 1
                assert first.get('/meu/sync/sessions/' + sid).json() == previous
                assert first.get('/meu/transfers').json()['root_id'] == generation
                assert first.get('/meu/transfers/download', params={
                    'root_id': generation, 'name': 'existing.txt'}).content == 'Αρχικό έργο'.encode()
                assert pc.post('/api/mobile-preview/devices/migrate', headers=headers(ticket(home, desc)),
                               json={'name': 'Λάζαρος'}).json()['device_id'] == device_id
                additional = pc.post('/api/mobile-preview/devices', headers=headers(ticket(home, desc)),
                                     json={'space_id': space['id'], 'label': 'Second phone'})
                assert additional.status_code == 200, additional.text
                second = pair(phones, additional.json()['code'])
                assert second.get('/meu/sync/sessions/' + sid).json() == previous
                assert first.headers['Authorization'] != second.headers['Authorization']
                outsider = pc.post('/api/mobile-preview/devices', headers=headers(ticket(home, desc)), json={'name': 'Other user'})
                assert outsider.status_code == 200, outsider.text
                isolated = pair(phones, outsider.json()['code'])
                assert isolated.get('/meu/sync/sessions/' + sid).status_code == 404

        with daemon(root, home, env, barrier=True, fixture='mobile_devices_daemon.py') as (_, desc):
            def restored():
                try:
                    result = first.get('/meu/sync/sessions/' + sid)
                    return result if result.status_code == 200 else None
                except httpx.TransportError:
                    return None
            assert wait_until(restored, timeout=45, what='same pinned phone restored after migration').json() == previous
            with httpx.Client(base_url=desc['api_origin'], trust_env=False, timeout=30) as pc:
                assert pc.delete('/api/mobile-preview/devices/' + device_id, headers=headers(ticket(home, desc))).status_code == 200
                try:
                    assert first.get('/meu/transfers').status_code == 410
                except httpx.TransportError:
                    pass  # Its individually revoked listener was closed.
                assert second.get('/meu/sync/sessions/' + sid).json() == previous
        assert (shared / 'existing.txt').read_bytes() == 'Αρχικό έργο'.encode()
    finally:
        for phone in phones:
            phone.close()
