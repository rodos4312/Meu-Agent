"""Browse and transfer within one selected root without sharing neighbouring trees."""
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from hermes_cli.meu_transfers import TransferFolder
from hermes_state import SessionDB


@pytest.fixture
def shared(tmp_path):
    db = SessionDB(tmp_path / 'state.db')
    root = tmp_path / 'shared'
    root.mkdir()
    folder = TransferFolder(SimpleNamespace(db=db, retiring=False, retired=False))
    folder.select(str(root))
    yield folder, root
    db.close()


def test_projects_browse_independently_and_roundtrip_exact_bytes(shared):
    folder, root = shared
    for name in ('Έργο Α', 'Έργο Β'):
        (root / name).mkdir()
        (root / name / 'report.txt').write_bytes(name.encode())
    overview = folder.listing()
    generation = overview['root_id']
    assert {item['name'] for item in overview['folders']} == {'Έργο Α', 'Έργο Β'}
    assert overview['files'] == []
    for name in ('Έργο Α', 'Έργο Β'):
        listing = folder.listing(name, generation)
        assert listing['path'] == name and listing['files'][0]['name'] == 'report.txt'
        stream, _ = folder.open_download('report.txt', generation, name, listing['directory_id'])
        with stream:
            assert stream.read() == name.encode()
        writer = folder.upload('phone.txt', generation, name, listing['directory_id'])
        try:
            writer.write(name.encode())
            writer.finish()
        finally:
            writer.close()
        assert (root / name / 'phone.txt').read_bytes() == name.encode()
    assert not (root / 'phone.txt').exists()


@pytest.mark.parametrize('path', ['../outside', '/outside', 'a/../b', r'a\b', 'C:/Windows',
                                  'a//b', 'a/', '.', 'a/.env', '.ssh', 'a/auth.json'])
def test_browser_rejects_noncanonical_and_sensitive_paths(shared, path):
    folder, _ = shared
    generation = folder.listing()['root_id']
    with pytest.raises(HTTPException):
        folder.listing(path, generation)


def test_changed_child_or_root_and_missing_identity_refuse_stale_upload(shared):
    folder, root = shared
    child = root / 'project'
    child.mkdir()
    generation = folder.listing()['root_id']
    listing = folder.listing('project', generation)
    child.rename(root / 'old-project')
    child.mkdir()
    for identity in (None, listing['directory_id']):
        with pytest.raises(HTTPException):
            folder.upload('phone.txt', generation, 'project', identity)
    assert not list(child.iterdir())
    folder.select('')
    with pytest.raises(HTTPException):
        folder.listing('project', generation)


def test_dashboard_routes_preserve_folder_scope_and_legacy_root_transfers(shared, monkeypatch):
    from hermes_cli import web_server
    from hermes_cli.web_routers import meu_transfers as routes

    folder, root = shared
    (root / 'Έργο').mkdir()
    app = FastAPI()
    app.include_router(routes.router)
    async def resolve(*_args):
        return folder
    def credential(request):
        if request.headers.get('authorization') != 'Bearer fixture':
            raise HTTPException(401)
    monkeypatch.setattr(routes, 'folder_for', resolve)
    monkeypatch.setattr(web_server, '_require_token', credential)
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer fixture'}
        assert client.get('/api/meu-transfers', params={'path': 'Έργο'}).status_code == 401
        generation = client.get('/api/meu-transfers', headers=headers).json()['root_id']
        listing = client.get('/api/meu-transfers', headers=headers,
                             params={'path': 'Έργο', 'root_id': generation}).json()
        params = {'name': 'document.bin', 'root_id': generation,
                  'path': 'Έργο', 'directory_id': listing['directory_id']}
        assert client.post('/api/meu-transfers/upload', headers=headers, params=params, content=b'phone').status_code == 200
        assert client.get('/api/meu-transfers/download', headers=headers, params=params).content == b'phone'
        assert (root / 'Έργο' / 'document.bin').read_bytes() == b'phone'
        legacy = {'name': 'document.bin', 'root_id': generation}
        assert client.post('/api/meu-transfers/upload', headers=headers, params=legacy, content=b'root').status_code == 200
        assert client.get('/api/meu-transfers/download', headers=headers, params=legacy).content == b'root'
        assert client.get('/api/meu-transfers', headers=headers,
                          params={'path': '../outside', 'root_id': generation}).status_code == 400


@pytest.mark.platforms('windows')
def test_windows_junction_is_never_listed_or_followed(shared, tmp_path):
    import subprocess

    folder, root = shared
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.txt').write_bytes(b'outside')
    junction = root / 'linked'
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)], check=True, capture_output=True)
    try:
        listing = folder.listing()
        assert listing['folders'] == []
        with pytest.raises(HTTPException):
            folder.listing('linked', listing['root_id'])
    finally:
        os.rmdir(junction)  # Remove only the junction, never its target tree.


@pytest.mark.platforms('windows')
def test_open_windows_upload_pins_its_directory_until_closed(shared):
    folder, root = shared
    child = root / 'project'
    child.mkdir()
    listing = folder.listing('project', folder.listing()['root_id'])
    writer = folder.upload('phone.txt', listing['root_id'], 'project', listing['directory_id'])
    try:
        writer.write(b'phone')
        with pytest.raises(PermissionError):
            child.rename(root / 'moved')
        writer.finish()
    finally:
        writer.close()
    child.rename(root / 'moved')
    assert (root / 'moved' / 'phone.txt').read_bytes() == b'phone'


@pytest.mark.platforms('posix')
def test_posix_symlink_directory_and_swapped_upload_do_not_escape(shared, tmp_path):
    folder, root = shared
    outside = tmp_path / 'outside'
    outside.mkdir()
    (root / 'linked').symlink_to(outside, target_is_directory=True)
    listing = folder.listing()
    assert listing['folders'] == []
    with pytest.raises(HTTPException):
        folder.listing('linked', listing['root_id'])
    child = root / 'project'
    child.mkdir()
    listing = folder.listing('project', listing['root_id'])
    writer = folder.upload('phone.txt', listing['root_id'], 'project', listing['directory_id'])
    try:
        writer.write(b'partial')
        child.rename(root / 'original')
        child.symlink_to(outside, target_is_directory=True)
        with pytest.raises(HTTPException):
            writer.finish()
    finally:
        writer.close()
    assert list(outside.iterdir()) == []
    assert list((root / 'original').iterdir()) == []
