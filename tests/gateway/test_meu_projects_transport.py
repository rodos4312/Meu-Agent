"""Real pinned pairing and admission fencing, using disposable stores only."""
import asyncio
import base64
import ipaddress
import ssl
from types import SimpleNamespace

from aiohttp import ClientSession
import pytest

from gateway.mobile_preview import MobilePreview
from gateway.session_authority import LiveSession, SessionAuthority
from gateway.session_contract import Principal, SessionRef, Submission
from hermes_state import SessionDB
from hermes_state_ids import new_session_id
from hermes_state_meu_projects import ProjectStore
from hermes_state_runtime import RuntimeStoreError, begin_runtime_epoch, list_session_admissions


def test_real_pinned_file_handoff_and_revoked_execution(tmp_path):
    asyncio.run(exercise(tmp_path))


async def exercise(tmp_path):
    root = tmp_path / 'project'; root.mkdir()
    (root / 'main.js').write_text('game source')
    replica = tmp_path / 'phone'; replica.mkdir()
    with SessionDB(tmp_path / 'pc-state' / 'state.db') as db, SessionDB(tmp_path / 'phone-state' / 'state.db') as phone:
        sid = new_session_id()
        for store in (db, phone):
            store.create_session(sid, source='gui')
        pid = ProjectStore(db).register(root, 'Game', [sid])['id']
        preview = MobilePreview(SimpleNamespace(db=db), ipaddress.IPv4Interface('127.0.0.1/8'), sync_profile=True)
        await preview.start()
        try:
            _, *fields = preview.code.split('.')
            origin, challenge, cert = [base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)) for value in fields]
            url = origin.decode() + '/meu/projects'
            tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
            async with ClientSession() as client:
                async with client.post(url, ssl=tls, json={'op': 'catalog'}) as response:
                    assert response.status == 401
                async with client.post(origin.decode() + '/meu/pair', ssl=tls, json={'challenge': challenge.decode()}) as response:
                    headers = {'Authorization': 'Bearer ' + (await response.json())['key']}

                async def call(request):
                    async with client.post(url, ssl=tls, headers=headers, json=request) as response:
                        assert response.status == 200, await response.text()
                        return await response.json()

                assert (await call({'op': 'catalog'}))['projects'][0]['id'] == pid
                async with client.post(url, ssl=tls, headers=headers, json={
                        'op': 'prepare', 'id': pid, 'transfer': 'steal', 'receiver': 'another-phone'}) as response:
                    assert response.status == 403
                offer = await call({'op': 'prepare', 'id': pid, 'transfer': 'one', 'receiver': 'phone-legacy'})
                target = ProjectStore(phone, 'phone-legacy')
                target.receive(offer, replica)
                data = await call({'op': 'chunk', 'id': pid, 'transfer': 'one', 'path': 'main.js', 'offset': 0})
                target.put_chunk(pid, 'one', 'main.js', 0, data['data'])
                assert target.verify(pid, 'one')['digest'] == offer['digest']
                grant = await call({'op': 'release', 'id': pid, 'transfer': 'one'})
                target.activate(grant)
                assert (replica / 'main.js').read_text() == 'game source'
                epoch = begin_runtime_epoch(db, instance_id='fixture')
                authority = SessionAuthority(SimpleNamespace(_draining=False), profile_id='owned',
                    instance_id='fixture', db=db, epoch=epoch)
                authority.sessions[sid] = LiveSession(None, 'route')
                actor = Principal('human', 'owned', frozenset({'session:submit', 'session:read'}), 'local')
                with pytest.raises(RuntimeStoreError, match='session_busy'):
                    await authority.submit(actor, Submission('new', SessionRef('owned', sid), {'text': 'do not run'}, 'queue'))
                assert list_session_admissions(db, session_id=sid) == []
        finally:
            await preview.close()
