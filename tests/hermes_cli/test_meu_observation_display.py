"""REST paints the paired draft, while canonical database reads stay unchanged."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_state import SessionDB
from hermes_state_ids import new_session_id
from hermes_state_meu_observation import observe, read_view


def test_read_side_pages_show_and_replace_live_progress_without_importing_it(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    home = tmp_path / '.hermes'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setattr('hermes_state.DEFAULT_DB_PATH', home / 'state.db')
    from hermes_cli.web_routers.sessions import manage_router
    app = FastAPI()
    app.include_router(manage_router)
    sid = new_session_id()
    with SessionDB(home / 'state.db') as db, TestClient(app) as client:
        db.create_session(sid, source='gui')
        db.append_message(sid, 'user', 'Work on the phone')
        view = read_view(db, sid)
        view.update(busy=True, draft='Visible while still working')
        observe(db, 'phone', view)
        path = f'/api/sessions/{sid}/meu-observation'
        response = client.get(path)
        assert response.status_code == 200, response.text
        projected = response.json()['observation']
        assert projected['draft'] == view['draft']
        assert projected['messages'] == []
        assert len(db.get_messages(sid)) == 1
        # Ordinary old-page reads must not receive a fabricated transcript tail.
        oldest = client.get(f'/api/sessions/{sid}/messages?limit=1&order=oldest').json()
        assert len(oldest['messages']) == 1
        assert not oldest['messages'][0].get('meu_observation')
        view['draft'] = 'Updated progress'
        observe(db, 'phone', view)
        newer = client.get(path).json()['observation']
        assert newer['draft'] == 'Updated progress'
        assert newer['messages'] == []
        canonical = client.get(f'/api/sessions/{sid}/messages?order=latest').json()['messages']
        assert [row['content'] for row in canonical] == ['Work on the phone']
