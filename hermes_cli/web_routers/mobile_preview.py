"""The local Meu desktop controls its temporary Android pairing listener."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from hermes_cli.web_routers.chat_ws import _authority_for_ticket_home
from hermes_cli.web_routers.webapp_access import owner_on_this_machine

from gateway.mobile_preview import PROFILE_PAIRING_KEY
from hermes_cli.web_routers.mobile_devices import router as _devices_router

logger = logging.getLogger(__name__)

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


def _pairing_store(state):
    return state.session_authority.db


async def _saved_pairing(state):
    raw = await asyncio.to_thread(_pairing_store(state).get_meta, PROFILE_PAIRING_KEY)
    if not raw:
        return None
    saved = json.loads(raw)
    return _validate_pairing(saved)


def _validate_pairing(saved):
    if (not isinstance(saved, dict) or not isinstance(saved.get("profile"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(saved.get("digest", "")))
            or not isinstance(saved.get("pem"), str)):
        raise ValueError("Invalid saved profile pairing")
    interfaces = [ipaddress.IPv4Interface(value) for value in saved["interfaces"]]
    if (not 1 <= len(interfaces) <= 2 or len(interfaces) != len(saved["ports"])
            or any(type(port) is not int or not 1 <= port <= 65535 for port in saved["ports"])):
        raise ValueError("Invalid saved profile endpoints")
    from gateway.mobile_preview import PRIVATE_NETWORKS, TAILSCALE_NETWORK
    if any(not any(interface.ip in network for network in (*PRIVATE_NETWORKS, TAILSCALE_NETWORK))
           for interface in interfaces):
        raise ValueError("Saved profile address must be private")
    return saved, interfaces


async def restore_mobile_profile_pairing(state):
    """Rebind the saved endpoints when the owning profile and network are available."""
    from gateway.mobile_preview import MobilePreview
    from gateway.session_authorities import serving_authorities

    while True:
        async with _lock(state):
            from hermes_cli.web_routers.mobile_devices import restore_personal_devices
            await restore_personal_devices(state)
            active = getattr(state, "mobile_preview", None)
            if active and (getattr(active.authority, "retiring", False)
                           or getattr(active.authority, "retired", False)):
                state.mobile_preview = None
                await active.close()
                active = None
            if active and active.token_digest:
                await active.restore_missing_sites()
            elif not active or active.state()["state"] == "off":
                try:
                    pairing = await _saved_pairing(state)
                    if pairing:
                        saved, interfaces = pairing
                        authority = next((item for item in serving_authorities(state.gateway_runner)
                                          if item.profile_id == saved["profile"]), None)
                        if authority:
                            preview = MobilePreview(
                                authority, interfaces[0], sync_profile=True,
                                sync_tailscale=interfaces[1] if len(interfaces) > 1 else None,
                                pairing_store=_pairing_store(state),
                            )
                            await preview.start(saved=saved)
                            state.mobile_preview = preview
                except OSError:
                    pass  # The PC may still be bringing up Wi-Fi or Tailscale.
                except (ValueError, KeyError, TypeError):
                    logger.warning("Saved Meu profile sync pairing could not be restored")
        await asyncio.sleep(15)


@router.get("")
async def mobile_status(request: Request):
    state, authority = _scope(request)
    preview = getattr(state, "mobile_preview", None)
    if preview:
        current = preview.state()
        if current["state"] != "off":
            return _state(current if preview.authority is authority else {"state": "other-profile"})
    pairing = await _saved_pairing(state)
    if pairing:
        saved, _ = pairing
        return _state({"state": "paired", "sync": True, "sync_profile": True, "offline": True}
                      if saved["profile"] == authority.profile_id else {"state": "other-profile"})
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


@router.post("/sync/profile")
async def start_mobile_profile_sync(request: Request):
    return await _start_mobile(request, remote=False, sync_profile=True)


@router.post("/internet")
async def start_mobile_internet(request: Request):
    return await _start_mobile(request, remote=True, internet=True)


async def _start_mobile(request: Request, *, remote: bool, internet: bool = False,
                        sync_session: str | None = None, sync_profile: bool = False):
    from aiohttp import ClientError
    from gateway.mobile_preview import MobilePreview, local_network, tailscale_network
    from gateway.session_policy import profile_config

    state, authority = _scope(request)
    sync_enabled = bool(sync_session or sync_profile)
    async with _lock(state):
        existing = getattr(state, "mobile_preview", None)
        if existing and existing.state()["state"] != "off":
            if existing.authority is not authority:
                raise HTTPException(409, "A phone connection is active in another profile.")
            if ((not sync_enabled and existing.remote != remote) or bool(existing.relay_url) != internet
                    or existing.sync_session != sync_session or existing.sync_profile != sync_profile):
                raise HTTPException(409, "Disconnect the phone before changing networks.")
            return _state(existing.state())
        if await _saved_pairing(state):
            raise HTTPException(409, "Disconnect the saved phone pairing first.")
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
                if sync_enabled:
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
                sync_session=sync_session, sync_tailscale=sync_tailscale, sync_profile=sync_profile,
                pairing_store=_pairing_store(state) if sync_profile else None,
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
        if preview and preview.authority is not authority and preview.state()["state"] != "off":
            raise HTTPException(409, "A phone connection is active in another profile.")
        if preview and preview.sync_profile:
            async with preview.lock:
                await _revoke_saved_pairing(state, authority)
                preview.challenge = None
                preview.token_digest = None
        else:
            await _revoke_saved_pairing(state, authority)
        state.mobile_preview = None
        if preview:
            await preview.close()
    return _state({"state": "off"})


async def _revoke_saved_pairing(state, authority):
    pairing = await _saved_pairing(state)
    if pairing:
        saved, _ = pairing
        if saved["profile"] != authority.profile_id:
            raise HTTPException(409, "A phone is paired to another profile.")
        await asyncio.to_thread(_pairing_store(state).set_meta, PROFILE_PAIRING_KEY, "")


async def close_mobile_preview(state):
    async with _lock(state):
        from hermes_cli.web_routers.mobile_devices import close_personal_devices
        await close_personal_devices(state)
        preview = getattr(state, "mobile_preview", None)
        state.mobile_preview = None
        if preview:
            await preview.close()


router.include_router(_devices_router)
