"""File transfers on the existing authenticated native/mobile connection."""
from __future__ import annotations

import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from hermes_cli.meu_transfers import CHUNK_BYTES, MAX_BYTES, TransferFolder, transfer_io
from hermes_cli.web_deps import late
from hermes_cli.web_routers._common import scoped_to_thread
from hermes_cli.web_routers.chat_ws import _authority_for_ticket_home
from hermes_cli.web_routers.webapp_access import owner_on_this_machine

def authenticated(request: Request):
    late("_require_token")(request)


router = APIRouter(prefix="/api/meu-transfers", dependencies=[Depends(authenticated)])


async def folder_for(request, profile):
    from hermes_constants import get_hermes_home

    def resolve():
        root = getattr(request.app.state, "session_authority", None)
        authority = _authority_for_ticket_home(root, str(get_hermes_home())) if root else None
        if authority is None:
            raise HTTPException(503, "Meu's backend is not ready.")
        return TransferFolder(authority)
    return await scoped_to_thread(profile, resolve)


class Selection(BaseModel):
    directory: str = Field(max_length=4096)


@router.post("/folder", dependencies=[Depends(owner_on_this_machine)])
async def select_folder(request: Request, selection: Selection, profile: str | None = None):
    # Resolve from the native grant, not a remote caller's query parameter.
    from hermes_cli.web_routers.mobile_preview import _scope

    _, authority = _scope(request)
    return await asyncio.to_thread(TransferFolder(authority).select, selection.directory)


@router.get("")
async def list_files(request: Request, profile: str | None = None):
    folder = await folder_for(request, profile)
    return await asyncio.to_thread(folder.listing)


@router.post("/upload")
async def upload(request: Request, name: str, root_id: str, profile: str | None = None):
    if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > MAX_BYTES:
        raise HTTPException(413, "File exceeds the transfer limit.")
    folder = await folder_for(request, profile)
    writer = folder.upload(name, root_id)
    try:
        async for chunk in request.stream():
            await transfer_io(writer.write, chunk)
        return await transfer_io(writer.finish)
    finally:
        writer.close()


@router.get("/download")
async def download(request: Request, name: str, root_id: str, profile: str | None = None):
    folder = await folder_for(request, profile)
    stream, size = folder.open_download(name, root_id)

    async def chunks():
        try:
            while chunk := await transfer_io(stream.read, CHUNK_BYTES):
                folder.grant(root_id)
                yield chunk
        finally:
            stream.close()
    return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
        "Content-Length": str(size), "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
