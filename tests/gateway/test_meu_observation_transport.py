"""Real pinned HTTPS observation, independent of the active writer's export gate."""
import asyncio
import base64
import ipaddress
import os
import ssl
from types import SimpleNamespace

from aiohttp import ClientSession

from gateway.mobile_preview import MobilePreview
from gateway.session_events import SessionEvents
from hermes_state import SessionDB
from hermes_state_ids import new_session_id


def test_pairing_reads_live_progress_without_resuming_or_submitting_a_turn(tmp_path):
    asyncio.run(exercise(tmp_path))


async def exercise(tmp_path):
    with SessionDB(tmp_path / 'pc.db') as db:
        sid = new_session_id()
        db.create_session(sid, source='gui')
        db.append_message(sid, 'user', 'Task from PC')
        baseline = db.get_messages(sid)
        events = SessionEvents()
        events.publish(sid, {}, event_type='message.start')
        events.publish(sid, {'text': 'Real live draft'}, event_type='message.delta')
        authority = SimpleNamespace(db=db, sessions={sid: SimpleNamespace(event_stream=events)})
        preview = MobilePreview(authority, ipaddress.IPv4Interface('127.0.0.1/8'), sync_profile=True)
        await preview.start()
        try:
            _, *fields = preview.code.split('.')
            origin, challenge, cert = [base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)) for value in fields]
            tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
            async with ClientSession() as client:
                async with client.post(origin.decode() + '/meu/pair', ssl=tls,
                                       json={'challenge': challenge.decode()}) as response:
                    grant = {'Authorization': 'Bearer ' + (await response.json())['key']}
                holder = f'pid={os.getpid()}:observation-transport'
                assert db.try_acquire_session_turn_lease(sid, holder)
                async with client.get(origin.decode() + '/meu/sync/sessions/' + sid, ssl=tls, headers=grant) as response:
                    assert response.status == 409
                async with client.get(origin.decode() + '/meu/observe/' + sid, ssl=tls, headers=grant) as response:
                    assert response.status == 200
                    view = (await response.json())['view']
                assert view['busy'] is True
                assert view['draft'] == 'Real live draft'
                assert db.get_messages(sid) == baseline
                # The same certificate cannot be bypassed by an unauthenticated view request.
                async with client.get(origin.decode() + '/meu/observe/' + sid, ssl=tls) as response:
                    assert response.status == 401
                view['draft'] = 'Phone display only'
                async with client.put(origin.decode() + '/meu/observe/' + sid, ssl=tls, headers=grant, json=view) as response:
                    assert response.status == 200
                assert db.get_messages(sid) == baseline
                db.release_session_turn_lease(sid, holder)
                events.publish(sid, {}, event_type='message.complete')
                assert events.display_draft == ''
        finally:
            await preview.close()
