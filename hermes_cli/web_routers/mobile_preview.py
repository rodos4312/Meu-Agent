"""The local Meu desktop controls its temporary Android pairing listener."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from hermes_cli.web_routers.chat_ws import _authority_for_ticket_home
from hermes_cli.web_routers.webapp_access import owner_on_this_machine

router = APIRouter(prefix="/api/mobile-preview", dependencies=[Depends(owner_on_this_machine)])


def _state(value):
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


def _scope(request):
    root = getattr(request.app.state, "session_authority", None)
    home = request.state.native_http_principal["profile_id"]
    authority = _authority_for_ticket_home(root, home) if root else None
    if authority is None or getattr(authority, "retiring", False):
        raise HTTPException(503, "Meu's local backend is not ready.")
    return request.app.state, authority


def _lock(state):
    if not hasattr(state, "mobile_preview_lock"):
        state.mobile_preview_lock = asyncio.Lock()
    return state.mobile_preview_lock


@router.get("")
async def mobile_status(request: Request):
    state, authority = _scope(request)
    preview = getattr(state, "mobile_preview", None)
    if preview:
        current = preview.state()
        if current["state"] != "off":
            return _state(current if preview.authority is authority else {"state": "other-profile"})
    return _state({"state": "off"})


@router.post("")
async def start_mobile(request: Request):
    from gateway.mobile_preview import MobilePreview, local_network

    state, authority = _scope(request)
    async with _lock(state):
        existing = getattr(state, "mobile_preview", None)
        if existing and existing.state()["state"] != "off":
            if existing.authority is not authority:
                raise HTTPException(409, "A phone connection is active in another profile.")
            return _state(existing.state())
        try:
            preview = MobilePreview(authority, await asyncio.to_thread(local_network))
            await preview.start()
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Meu could not start pairing on a private local network.") from exc
        state.mobile_preview = preview
        return _state(preview.state())


@router.delete("")
async def stop_mobile(request: Request):
    state, authority = _scope(request)
    async with _lock(state):
        preview = getattr(state, "mobile_preview", None)
        if preview:
            if preview.authority is not authority and preview.state()["state"] != "off":
                raise HTTPException(409, "A phone connection is active in another profile.")
            state.mobile_preview = None
            await preview.close()
    return _state({"state": "off"})


async def close_mobile_preview(state):
    async with _lock(state):
        preview = getattr(state, "mobile_preview", None)
        state.mobile_preview = None
        if preview:
            await preview.close()
