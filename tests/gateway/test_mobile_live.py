"""Two real sockets share one authority, one FIFO and replay after a gap."""
import asyncio
import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import threading
from types import SimpleNamespace

import httpx
import pytest
from websockets.asyncio.client import connect

from tests.gateway.fixtures.local_recovery_probe import child_env, daemon, websocket
from tests.gateway.test_native_http_auth import headers, ticket
from tests.gateway.test_mobile_preview import _WeatherModel


class Reader:
    def __init__(self, socket):
        self.socket, self.events, self.pending = socket, [], {}
        self.changed = asyncio.Event()
        self.task = asyncio.create_task(self.read())
        self.counter = 0

    async def read(self):
        async for raw in self.socket:
            for line in raw.splitlines():
                frame = json.loads(line)
                if frame.get('id') in self.pending:
                    self.pending[frame['id']].set_result(frame)
                else:
                    self.events.append(frame)
                    self.changed.set()

    async def call(self, method, **params):
        self.counter += 1
        key = str(self.counter)
        future = self.pending[key] = asyncio.get_running_loop().create_future()
        await self.socket.send(json.dumps({'jsonrpc': '2.0', 'id': key, 'method': method, 'params': params}))
        try:
            return await asyncio.wait_for(future, 30)
        finally:
            self.pending.pop(key, None)

    async def wait_event(self, kind):
        async with asyncio.timeout(30):
            while not any(frame.get('params', {}).get('type') == kind for frame in self.events):
                self.changed.clear()
                await self.changed.wait()


def test_pc_and_paired_phone_share_fifo_and_replay_without_resubmit(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home, user = tmp_path / 'state', tmp_path / 'user'
    home.mkdir()
    user.mkdir()
    model = ThreadingHTTPServer(('127.0.0.1', 0), _WeatherModel)
    model.requests = []
    model.blocked, model.release = threading.Event(), threading.Event()
    threading.Thread(target=model.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{model.server_port}/v1'
    (home / 'config.yaml').write_text(json.dumps({
        'model': {'provider': 'custom', 'default': 'local-wire-stub', 'base_url': base},
        'gateway': {'multiplex_profiles': False}, 'platform_toolsets': {'cli': []},
        'auxiliary': {'title_generation': {'enabled': False}},
    }))
    env = child_env()
    env.update(HOME=str(user), USERPROFILE=str(user), HERMES_HOME=str(home), PYTHONPATH=str(root),
               OPENAI_API_KEY='loopback-fixture', OPENAI_BASE_URL=base, PYTHONUNBUFFERED='1',
               FIRECRAWL_API_KEY='loopback-fixture-no-live-calls')
    try:
        with daemon(root, home, env, barrier=True, fixture='mobile_preview_daemon.py') as (_, desc):
            asyncio.run(_exercise(home, desc, model))
    finally:
        model.release.set()
        model.shutdown()
        model.server_close()


async def _exercise(home, desc, model):
    with httpx.Client(base_url=desc['api_origin'], trust_env=False, timeout=30) as desktop:
        owner = headers(ticket(home, desc))
        started = desktop.post('/api/mobile-preview/sync/profile', headers=owner)
        assert started.status_code == 200, started.text
        _version, *parts = started.json()['code'].split('.')
        origins, challenge, certificate = [base64.urlsafe_b64decode(p + '=' * (-len(p) % 4)) for p in parts]
        origin = origins.decode().splitlines()[0]
        tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(certificate))
        with httpx.Client(base_url=origin, verify=tls, trust_env=False) as client:
            key = client.post('/meu/pair', json={'challenge': challenge.decode()}).json()['key']
            assert client.get('/meu/sync/sessions?live=1', headers={'Authorization': 'Bearer ' + key}).json()['live_chat'] == 1
        live = origin.replace('https:', 'wss:') + '/meu/live'
        grant = {'Authorization': 'Bearer ' + key}
        async with websocket(home, desc) as pc_socket, connect(live, ssl=tls, additional_headers=grant) as phone_socket:
            pc, phone = Reader(pc_socket), Reader(phone_socket)
            created = await pc.call('session.create', source='gui', request_id='live-test', toolsets=['web'])
            sid = created['result']['session_id']
            opened = await phone.call('session.resume', session_id=sid, source='desktop')
            assert 'result' in opened, opened
            assert opened['result']['session_id'] == sid
            from tests.gateway.fixtures.mobile_observation import verify_observed_submission
            await verify_observed_submission(pc, desktop, lambda: headers(ticket(home, desc)), origin, tls, grant, sid, model)
            ack = await pc.call('prompt.submit', session_id=sid, input_id='pc-one', text='BLOCK_STARTED')
            assert 'result' in ack, ack
            started = await asyncio.to_thread(model.blocked.wait, 35)
            assert started, {'receipt': await pc.call('prompt.receipt', session_id=sid,
                admission_id=ack['result']['admission_id']), 'events': pc.events[-4:],
                'model_requests': len(model.requests)}
            # Phone is passive while the PC starts work: it still gets the live stream.
            await phone.wait_event('message.start')
            with httpx.Client(base_url=origin, verify=tls, trust_env=False) as client:
                live_view = client.get('/meu/live/sessions/' + sid, headers=grant)
                assert live_view.status_code == 200
                assert live_view.json()['live_view']['id'] == sid
            async with connect(live, ssl=tls, additional_headers=grant) as retry_socket:
                retry = Reader(retry_socket)
                assert 'result' in await retry.call('session.resume', session_id=sid)
                attempts = await asyncio.gather(*[
                    viewer.call('prompt.submit', session_id=sid, client_turn_id='phone-two', text='MOBILE_WEB_TEST')
                    for viewer in (phone, retry)])
                assert sorted(result['result']['duplicate'] for result in attempts) == [False, True]
                assert attempts[0]['result']['server_turn_id'] == attempts[1]['result']['server_turn_id']
                queued = attempts[0]
                await retry_socket.close()
                await retry.task
            assert queued['result']['state'] == 'accepted', queued
            duplicate = await phone.call('prompt.submit', session_id=sid, client_turn_id='phone-two', text='MOBILE_WEB_TEST')
            assert duplicate['result']['duplicate'] is True, duplicate
            assert duplicate['result']['server_turn_id'] == queued['result']['server_turn_id']
            model.release.set()
            await phone.wait_event('message.complete')
            async with asyncio.timeout(30):
                for _attempt in range(600):
                    receipt = await phone.call('turn.status', session_id=sid, client_turn_id='phone-two')
                    if receipt['result'].get('state') == 'terminal':
                        break
                    await asyncio.sleep(.05)
                else:
                    pytest.fail('The shared phone admission did not settle')
            history = await phone.call('session.history', session_id=sid)
            assert 'result' in history, history
            serialized = json.dumps(history['result'])
            assert 'MOBILE_WEB_TEST' in serialized and 'BLOCK_STARTED' in serialized
            assert 'fixture forecast' in serialized  # The shared agent actually ran its web tool.
            await pc.wait_event('message.complete')
            cursor = opened['result']['last_sequence']
            epoch = opened['result']['replay_epoch']
            await phone_socket.close()
            await phone.task
            async with connect(live, ssl=tls, additional_headers=grant) as reconnect_socket:
                reconnected = Reader(reconnect_socket)
                replay = await reconnected.call('session.events.since', session_id=sid, replay_epoch=epoch, last_seen=cursor)
                assert 'result' in replay, replay
                assert replay['result']['snapshot_required'] is False
                assert replay['result']['events']
                await reconnected.call('session.resume', session_id=sid)
                same = await reconnected.call('prompt.submit', session_id=sid, client_turn_id='phone-two', text='MOBILE_WEB_TEST')
                assert same['result']['duplicate'] is True
                assert same['result']['server_turn_id'] == queued['result']['server_turn_id']
                for method, params in (
                    ('config.set', {'key': 'model', 'value': 'foreign'}),
                    ('session.resume', {'session_id': sid, 'title': 'another chat'}),
                    ('session.history', {'session_id': sid, 'profile': 'foreign'}),
                ):
                    rejected = await reconnected.call(method, **params)
                    assert rejected['error']['code'] == 4003, rejected
                await reconnect_socket.close()
                await reconnected.task
            await pc_socket.close()
            await pc.task
    user_turns = [next(m['content'] for m in reversed(r['messages']) if m['role'] == 'user') for r in model.requests]
    assert user_turns == ['BLOCK_STARTED', 'MOBILE_WEB_TEST', 'MOBILE_WEB_TEST'], user_turns


@pytest.mark.asyncio
async def test_live_events_cannot_cross_personal_spaces_or_survive_revocation(tmp_path):
    from fastapi import HTTPException
    from gateway.mobile_live import LiveScope, _Socket
    from gateway.mobile_spaces import PersonalDevices
    from hermes_cli.meu_transfers import TransferFolder
    from hermes_state import SessionDB

    with SessionDB(tmp_path / 'state.db') as db:
        authority = SimpleNamespace(db=db, profile_id=str(tmp_path), instance_id='test', epoch=1)
        folder = tmp_path / 'files'
        folder.mkdir()
        TransferFolder(authority).select(str(folder))
        devices = PersonalDevices(db)
        first, space = devices.add(authority, name='Πρώτος')
        _, other = devices.add(authority, name='Δεύτερος')
        ids = ['local-' + char * 64 for char in 'abc']
        for sid, owner in zip(ids, [space, other, None]):
            db.create_session(sid, source='gui')
            if owner:
                db.set_meta('meu.space.session:' + sid, owner['id'])
        preview = SimpleNamespace(authority=authority, personal_devices=devices, device_id=first['id'],
                                  personal_space=space['id'], loop=asyncio.get_running_loop(), deadline=float('inf'))
        scope = LiveScope(preview)
        assert scope.owns(ids[0])
        assert not scope.owns(ids[1]) and not scope.owns(ids[2])
        delivered = []

        class Receiver:
            async def send_str(self, raw):
                delivered.extend(json.loads(line) for line in raw.splitlines())

        socket = _Socket(Receiver(), scope)
        frames = [json.dumps({'jsonrpc': '2.0', 'method': 'event', 'params': {
            'type': 'message.complete', 'session_id': sid, 'payload': {'text': sid}}}) for sid in ids]
        await socket.send_text('\n'.join(frames))
        assert [frame['params']['session_id'] for frame in delivered if 'session_id' in frame['params']] == [ids[0]]
        assert all(sid not in json.dumps(delivered) for sid in ids[1:])
        before_revoke = len(delivered)
        devices.revoke(authority.profile_id, first['id'])
        with pytest.raises(HTTPException):
            await socket.send_text(frames[0])
        assert len(delivered) == before_revoke
