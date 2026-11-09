"""Native owner controls for named personal spaces and independent device pairing."""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from gateway.mobile_spaces import PersonalDevices

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/devices')


def registry(state):
    if not hasattr(state, 'personal_devices'):
        state.personal_devices = PersonalDevices(state.session_authority.db)
    if not hasattr(state, 'personal_device_listeners'):
        state.personal_device_listeners = {}
    return state.personal_devices


@router.get('')
async def devices(request: Request):
    from hermes_cli.web_routers.mobile_preview import _scope, _state
    state, authority = _scope(request)
    value = await asyncio.to_thread(registry(state).public, authority.profile_id)
    for device in value['devices']:
        listener = state.personal_device_listeners.get(device['id'])
        status = listener.state() if listener else {'state': 'off'}
        device['state'] = status['state']
        device['last_contact'] = status.get('last_contact') or device['last_contact']
        device['offline'] = status.get('offline', True)
    value['management_version'] = 2
    value['legacy'] = await legacy_status(state, authority)
    return _state(value)


async def legacy_status(state, authority):
    from hermes_cli.web_routers.mobile_preview import _saved_pairing
    preview = getattr(state, 'mobile_preview', None)
    if preview and preview.state()['state'] != 'off':
        if preview.authority is not authority:
            return {'state': 'other-profile', 'can_migrate': False}
        return {'state': preview.state()['state'],
                'can_migrate': bool(preview.sync_profile and preview.token_digest),
                'kind': 'profile' if preview.sync_profile else 'temporary'}
    saved = await _saved_pairing(state)
    if saved:
        own = saved[0]['profile'] == authority.profile_id
        return {'state': 'paired' if own else 'other-profile', 'can_migrate': own, 'kind': 'profile'}
    return None


class Enrolment(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    space_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    label: str | None = Field(default=None, max_length=80)
    owner: bool = False


def device_networks():
    """Retain private VPN reachability without requiring a second pairing form."""
    from gateway.mobile_preview import local_network, tailscale_network
    interfaces = []
    for discover in (local_network, tailscale_network):
        try:
            interface = discover()
            if interface not in interfaces:
                interfaces.append(interface)
        except (ValueError, OSError):
            pass
    if not interfaces:
        raise HTTPException(503, 'Connect the PC to Wi-Fi or Tailscale first.')
    return interfaces


@router.post('')
async def add_device(request: Request, selection: Enrolment):
    from gateway.mobile_preview import MobilePreview
    from hermes_cli.web_routers.mobile_preview import _lock, _scope, _state

    state, authority = _scope(request)
    if bool(selection.name) == bool(selection.space_id) or (selection.owner and selection.space_id):
        raise HTTPException(422, 'Enter a new name or select an existing personal space.')
    async with _lock(state):
        service = registry(state)
        # Probe connectivity before creating a folder or an enrolment record.
        interfaces = await asyncio.to_thread(device_networks)
        if selection.owner:
            device, space = await asyncio.to_thread(service.add_owner, authority,
                                                    name=selection.name, label=selection.label)
        else:
            device, space = await asyncio.to_thread(service.add, authority, name=selection.name,
                                                   space_id=selection.space_id, label=selection.label)
        preview = MobilePreview(authority, interfaces[0], sync_profile=True,
                                sync_tailscale=interfaces[1] if len(interfaces) > 1 else None, pairing_store=service.store,
                                personal_devices=service, device_id=device['id'])
        try:
            await preview.start()
        except BaseException:
            await asyncio.to_thread(service.revoke, authority.profile_id, device['id'])
            await preview.close()
            raise
        state.personal_device_listeners[device['id']] = preview
        return _state({'device_id': device['id'], 'space_id': space['id'], 'space_name': space['name'], **preview.state()})


class Migration(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=80)


@router.post('/migrate')
async def migrate_device(request: Request, selection: Migration):
    from hermes_cli.web_routers.mobile_preview import _lock, _saved_pairing, _scope, _state
    state, authority = _scope(request)

    async def finish():
        from gateway.mobile_device_migration import migrate_owner
        saved = await _saved_pairing(state)
        if saved and saved[0]['profile'] != authority.profile_id:
            raise HTTPException(409, 'Switch to the profile that owns the existing connection.')
        service = registry(state)
        device, space = await asyncio.to_thread(migrate_owner, service, authority,
            saved[0] if saved else None, name=selection.name, label=selection.label)
        preview = getattr(state, 'mobile_preview', None)
        if preview and preview.authority is authority and preview.sync_profile:
            preview.personal_devices, preview.device_id = service, device['id']
            preview.personal_space = None  # The pre-existing PC-owner grant stays identical.
            state.personal_device_listeners[device['id']] = preview
            state.mobile_preview = None
        return _state({'migrated': True, 'device_id': device['id'], 'space_id': space['id'], 'space_name': space['name']})

    async with _lock(state):
        # Once committed, complete the in-memory handoff even if the HTTP viewer
        # disconnects. A process crash restores the same saved ports/pin/key.
        task = asyncio.create_task(finish())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise


@router.delete('/{device_id}')
async def remove_device(request: Request, device_id: str):
    from hermes_cli.web_routers.mobile_preview import _lock, _scope, _state
    state, authority = _scope(request)
    async with _lock(state):
        service = registry(state)
        # Revocation is durable before the listener is closed; active transfers
        # also recheck it through their existing folder lease.
        await asyncio.to_thread(service.revoke, authority.profile_id, device_id)
        preview = state.personal_device_listeners.pop(device_id, None)
        if preview:
            await preview.close()
    return _state({'disconnected': True})


async def restore_personal_devices(state):
    from gateway.mobile_preview import MobilePreview
    from gateway.session_authorities import serving_authorities
    from hermes_cli.web_routers.mobile_preview import _validate_pairing
    service = registry(state)
    for device_id, preview in list(state.personal_device_listeners.items()):
        if getattr(preview.authority, 'retiring', False) or getattr(preview.authority, 'retired', False):
            await preview.close()
            del state.personal_device_listeners[device_id]
        elif preview.token_digest:
            await preview.restore_missing_sites()
    for device in await asyncio.to_thread(service.saved):
        if device['id'] in state.personal_device_listeners:
            continue
        try:
            saved, interfaces = _validate_pairing(device['pairing'])
            if saved['profile'] != device['profile']:
                raise ValueError('Profile binding changed')
            authority = next((a for a in serving_authorities(state.gateway_runner)
                              if a.profile_id == device['profile']), None)
            if authority is None:
                continue
            preview = MobilePreview(authority, interfaces[0], sync_profile=True,
                                    sync_tailscale=interfaces[1] if len(interfaces) > 1 else None,
                                    pairing_store=service.store, personal_devices=service, device_id=device['id'])
            await preview.start(saved=saved)
            state.personal_device_listeners[device['id']] = preview
        except OSError:
            pass  # Restore on the next existing network recovery tick.
        except (ValueError, KeyError, TypeError):
            logger.warning('A personal device could not be restored; its files were kept')


async def close_personal_devices(state):
    listeners = getattr(state, 'personal_device_listeners', {})
    state.personal_device_listeners = {}
    for preview in listeners.values():
        await preview.close()
