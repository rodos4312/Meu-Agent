"""Read-side pairing must not grant a second native execution owner."""
import json

import httpx


async def verify_observed_submission(pc, desktop, fresh_owner, origin, tls, grant, sid, model):
    view = {'id': sid, 'messages': [], 'busy': True, 'draft': 'Phone is building'}
    with httpx.Client(base_url=origin, verify=tls, trust_env=False) as client:
        response = client.put('/meu/observe/' + sid, headers=grant, json=view)
        assert response.status_code == 200, response.text
        observed = desktop.get('/api/sessions/' + sid + '/meu-observation', headers=fresh_owner())
        assert observed.status_code == 200, observed.text
        assert observed.json()['observation']['draft'] == 'Phone is building'
        refused = await pc.call('prompt.submit', session_id=sid, input_id='observation-only-input', text='Do not run twice')
        assert 'session_busy' in json.dumps(refused), refused
        assert model.requests == []
        # Clearing the temporary view grants no work either. The caller can
        # now continue its ordinary, explicit native submission test.
        view.update(busy=False, draft='')
        assert client.put('/meu/observe/' + sid, headers=grant, json=view).status_code == 200
        assert desktop.get('/api/sessions/' + sid + '/meu-observation', headers=fresh_owner()).json()['observation'] is None
