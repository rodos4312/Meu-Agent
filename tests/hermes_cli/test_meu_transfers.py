"""Actual profile stores and HTTP streams for the selected transfer folder."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from hermes_state import SessionDB
from hermes_cli.meu_transfers import TransferFolder
from hermes_cli.web_routers import meu_transfers as routes


@pytest.fixture
def folders(tmp_path):
    stores = [SessionDB(tmp_path / name / "state.db") for name in ("one", "two")]
    roots = [tmp_path / name for name in ("shared-one", "shared-two")]
    for root in roots:
        root.mkdir()
    owners = [SimpleNamespace(db=db, retiring=False, retired=False) for db in stores]
    result = [TransferFolder(owner) for owner in owners]
    for folder, root in zip(result, roots):
        folder.select(str(root))
    yield result, roots
    for db in stores:
        db.close()


def test_persistence_exact_bytes_exclusive_collision_and_profile_isolation(folders):
    (one, two), (root, _) = folders
    generation = one.listing()["root_id"]
    payload = bytes(range(256)) * 4097
    writer = one.upload("δοκιμή.zip", generation)
    try:
        for offset in range(0, len(payload), 8192):
            writer.write(payload[offset:offset + 8192])
        assert not (root / "δοκιμή.zip").exists()
        assert writer.finish()["size"] == len(payload)
    finally:
        writer.close()
    assert TransferFolder(one.authority).listing()["files"][0]["name"] == "δοκιμή.zip"
    reopened = SessionDB(one.db.db_path)
    try:
        restored = TransferFolder(SimpleNamespace(db=reopened, retiring=False, retired=False)).listing()
        assert restored["root_id"] == generation and restored["files"][0]["name"] == "δοκιμή.zip"
    finally:
        reopened.close()
    stream, size = one.open_download("δοκιμή.zip", generation)
    with stream:
        assert size == len(payload) and stream.read() == payload
    with pytest.raises(HTTPException) as error:
        one.upload("δοκιμή.zip", generation)
    assert error.value.status_code == 409
    assert two.listing()["files"] == []
    with pytest.raises(HTTPException) as error:
        two.open_download("δοκιμή.zip", generation)
    assert error.value.status_code == 409


def test_partial_cancel_revocation_and_collision_at_commit_leave_no_partial(folders):
    (folder, _), (root, _) = folders
    generation = folder.listing()["root_id"]
    writer = folder.upload("partial.txt", generation)
    writer.write(b"partial")
    writer.close()  # disconnected/cancelled HTTP body
    assert list(root.iterdir()) == []
    writer = folder.upload("collision.txt", generation)
    try:
        writer.write(b"new")
        (root / "collision.txt").write_bytes(b"original")
        with pytest.raises(HTTPException):
            writer.finish()
    finally:
        writer.close()
    assert (root / "collision.txt").read_bytes() == b"original"
    writer = folder.upload("revoked.txt", generation)
    try:
        writer.write(b"first")
        folder.select("")
        with pytest.raises(HTTPException):
            writer.write(b"second")
        with pytest.raises(HTTPException):
            writer.finish()
    finally:
        writer.close()
    assert not (root / "revoked.txt").exists()
    assert not list(root.glob(".meu-transfer-*"))


@pytest.mark.parametrize("name", ["../outside", "a/b", "a\\b", "/etc/passwd", "C:other", ".env", "auth.json", "NUL.txt", "bad."])
def test_remote_names_cannot_escape_or_expose_secrets(folders, name):
    (folder, _), _ = folders
    with pytest.raises(HTTPException):
        folder.upload(name, folder.listing()["root_id"])


def test_http_auth_local_only_selection_and_streaming(folders, monkeypatch):
    (folder, _), (root, _) = folders
    app = FastAPI()
    app.include_router(routes.router)
    async def resolve(_request, _profile):
        return folder
    monkeypatch.setattr(routes, "folder_for", resolve)
    from hermes_cli import web_server
    def credential(request):
        if request.headers.get("authorization") != "Bearer fixture":
            raise HTTPException(401)
    monkeypatch.setattr(web_server, "_require_token", credential)
    with TestClient(app) as client:
        assert client.get("/api/meu-transfers").status_code == 401
        headers = {"Authorization": "Bearer fixture"}
        assert client.post("/api/meu-transfers/folder", headers=headers, json={"directory": str(root)}).status_code == 403
        listing = client.get("/api/meu-transfers", headers=headers)
        assert listing.status_code == 200, listing.text
        generation = listing.json()["root_id"]
        query = {"name": "roundtrip.bin", "root_id": generation}
        payload = b"real streamed bytes" * 17000
        uploaded = client.post("/api/meu-transfers/upload", headers=headers, params=query, content=iter([payload[:100], payload[100:]]))
        assert uploaded.status_code == 200, uploaded.text
        downloaded = client.get("/api/meu-transfers/download", headers=headers, params=query)
        assert downloaded.content == payload
        assert downloaded.headers["content-disposition"].startswith("attachment")


def test_http_disconnect_cleans_staging(folders, monkeypatch):
    (folder, _), (root, _) = folders
    async def resolve(*_args):
        return folder
    monkeypatch.setattr(routes, "folder_for", resolve)
    async def body():
        yield b"incomplete"
        raise asyncio.CancelledError()
    request = SimpleNamespace(headers={}, stream=body)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(routes.upload(request, "cancelled.bin", folder.listing()["root_id"]))
    assert list(root.iterdir()) == []


def test_limit_and_disabled_folder_refuse_without_publishing(folders, monkeypatch):
    from hermes_cli import meu_transfers
    (folder, _), (root, _) = folders
    generation = folder.listing()["root_id"]
    monkeypatch.setattr(meu_transfers, "MAX_BYTES", 4)
    writer = folder.upload("large.bin", generation)
    try:
        with pytest.raises(HTTPException) as error:
            writer.write(b"12345")
        assert error.value.status_code == 413
    finally:
        writer.close()
    assert list(root.iterdir()) == []


def test_cancel_waits_for_its_disk_operation_before_releasing_resources():
    import threading
    from hermes_cli.meu_transfers import transfer_io

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def disk_write():
        started.set()
        assert release.wait(30)
        finished.set()
    async def check():
        task = asyncio.create_task(transfer_io(disk_write))
        try:
            assert await asyncio.to_thread(started.wait, 30)
            task.cancel()
            await asyncio.sleep(0)  # process cancellation, without a timing delay
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set()
        finally:
            release.set()
            if not task.done():
                await task
    asyncio.run(check())


@pytest.mark.platforms("posix")
def test_symlinks_and_special_files_cannot_be_read(folders):
    import os
    (folder, _), (root, outside) = folders
    (outside / "private.txt").write_text("outside")
    (root / "linked.txt").symlink_to(outside / "private.txt")
    os.mkfifo(root / "pipe")
    generation = folder.listing()["root_id"]
    assert folder.listing()["files"] == []
    for name in ("linked.txt", "pipe"):
        with pytest.raises(HTTPException):
            folder.open_download(name, generation)
