"""The local Meu desktop controls its temporary Android pairing listener."""

from __future__ import annotations

import asyncio
import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
    return await _start_mobile(request, remote=False)


@router.post("/tailscale")
async def start_mobile_tailscale(request: Request):
    return await _start_mobile(request, remote=True)


class MobileSyncSelection(BaseModel):
    session_id: str = Field(max_length=70)


@router.post("/sync")
async def start_mobile_sync(request: Request, selection: MobileSyncSelection):
    return await _start_mobile(request, remote=False, sync_session=selection.session_id)


@router.post("/internet")
async def start_mobile_internet(request: Request):
    return await _start_mobile(request, remote=True, internet=True)


async def _start_mobile(request: Request, *, remote: bool, internet: bool = False,
                        sync_session: str | None = None):
    from aiohttp import ClientError
    from gateway.mobile_preview import MobilePreview, local_network, tailscale_network
    from gateway.session_policy import profile_config

    state, authority = _scope(request)
    async with _lock(state):
        existing = getattr(state, "mobile_preview", None)
        if existing and existing.state()["state"] != "off":
            if existing.authority is not authority:
                raise HTTPException(409, "A phone connection is active in another profile.")
            if ((sync_session is None and existing.remote != remote) or bool(existing.relay_url) != internet
                    or existing.sync_session != sync_session):
                raise HTTPException(409, "Disconnect the phone before changing networks.")
            return _state(existing.state())
        if sync_session is not None:
            try:
                await asyncio.to_thread(authority.db.export_meu_sync_history, sync_session)
            except ValueError as exc:
                raise HTTPException(422, "Select a supported conversation in this profile.") from exc
        try:
            relay_url = None
            sync_tailscale = None
            if internet:
                config = await asyncio.to_thread(profile_config, authority)
                gateway = config.get("gateway")
                relay_url = gateway.get("mobile_relay_url") if isinstance(gateway, dict) else None
                if not isinstance(relay_url, str) or not relay_url.strip():
                    raise HTTPException(503, "The Meu internet relay has not been configured.")
                interface = ipaddress.IPv4Interface("127.0.0.1/32")
            else:
                if sync_session:
                    try:
                        sync_tailscale = await asyncio.to_thread(tailscale_network)
                    except ValueError:
                        pass  # Local pairing still works without the VPN.
                try:
                    interface = await asyncio.to_thread(tailscale_network if remote else local_network)
                except (OSError, ValueError):
                    if sync_tailscale is None:
                        raise
                    interface, sync_tailscale = sync_tailscale, None
                    remote = True
            preview = MobilePreview(
                authority, interface, remote=remote, relay_url=relay_url,
                sync_session=sync_session, sync_tailscale=sync_tailscale,
            )
            await preview.start()
        except (ClientError, OSError, TimeoutError, ValueError) as exc:
            raise HTTPException(503, "Meu could not start the selected mobile connection.") from exc
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
