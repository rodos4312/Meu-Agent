"""Project handoff uses the existing revocable, pinned, profile-scoped listener."""
import asyncio
from pathlib import Path

from aiohttp import web
from fastapi import HTTPException
from hermes_state_errors import SessionActiveWriteGuardError
from hermes_state_meu_projects import ProjectStore, identity
from meu_project_files import portable


def operate(store, request, *, receive_root=None):
    """Same operation dispatcher in the native phone process and PC transport."""
    if not isinstance(request, dict):
        raise ValueError('invalid_project_request')
    op = request.get('op')
    if op == 'catalog':
        return store.catalog()
    if op == 'prepare':
        return store.prepare(request['id'], request['receiver'], request['transfer'])
    if op == 'chunk':
        return store.chunk(request['id'], request['transfer'], request['path'], request['offset'])
    if op == 'receive':
        offer = request['offer']
        portable(offer['name'])
        identity(offer['id'])
        with store.db._read_ctx() as conn:
            record = next((item for item in store._records(conn) if item['id'] == offer['id'] and item['space'] == store.space), None)
        if record is None:
            if receive_root is None:
                raise ValueError('select_project_directory')
            root = Path(receive_root) / (offer['name'] + '-' + offer['id'][:8])
            root.mkdir(exist_ok=True)
        else:
            root = Path(record['root'])
        return store.receive(offer, root)
    if op == 'put':
        return store.put_chunk(request['id'], request['transfer'], request['path'], request['offset'], request['data'])
    if op == 'verify':
        return store.verify(request['id'], request['transfer'])
    if op == 'release':
        return store.release(request['id'], request['transfer'])
    if op == 'activate':
        return store.activate(request['grant'])
    if op == 'cancel':
        return store.cancel_offer(request['id'], request['transfer'])
    if op == 'discard':
        return store.discard_receive(request['id'], request['transfer'])
    raise ValueError('invalid_project_operation')


def mount(app, preview):
    async def handle(request):
        if not preview.sync_profile:
            raise web.HTTPForbidden()
        store = ProjectStore(preview.authority.db, space=preview.personal_space)
        peer = 'phone-' + (preview.device_id or 'legacy')
        try:
            payload = await preview._json(request)
            op = payload.get('op')
            if op == 'prepare' and payload.get('receiver') != peer:
                raise web.HTTPForbidden()
            if op == 'receive' and payload.get('offer', {}).get('sender') != peer:
                raise web.HTTPForbidden()
            if op == 'activate' and payload.get('grant', {}).get('owner') != 'pc':
                raise web.HTTPForbidden()
            # Knowledge of a project ID never grants a different paired device ownership.
            pid = payload.get('id') or payload.get('offer', {}).get('id') or payload.get('grant', {}).get('id')
            if pid and op not in {'receive'}:
                with store.db._read_ctx() as conn:
                    item = store._get(conn, pid)
                # An unstarted cancellation only fences its attempt id; it never
                # changes the owner or cancels another device's offered transfer.
                cancel_unstarted = op == 'cancel' and item['phase'] == 'ready' and item['owner'] == 'pc'
                if item['owner'] not in {'pc', peer} or (op in {'chunk', 'release', 'cancel'} and
                        item.get('receiver') != peer and not cancel_unstarted):
                    raise web.HTTPForbidden()
            if op == 'receive':
                with store.db._read_ctx() as conn:
                    registered = any(item['id'] == pid and item['space'] == store.space for item in store._records(conn))
                if registered:
                    # Returning an explicitly selected project does not require
                    # a second, unrelated general-purpose file-sharing grant.
                    root = None
                else:
                    from hermes_cli.meu_transfer_spaces import MobileTransferFolder
                    root, _ = MobileTransferFolder(preview).grant()
            else:
                root = None
            result = await asyncio.to_thread(operate, store, payload, receive_root=root)
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except SessionActiveWriteGuardError:
            return web.json_response({'status': 'busy'}, status=409)
        except LookupError:
            raise web.HTTPNotFound() from None
        except HTTPException as error:
            return web.json_response({'status': 'refused', 'reason': error.detail}, status=error.status_code)
        except OSError:
            return web.json_response({'status': 'refused', 'reason': 'project_storage_unavailable'}, status=409)
        except (ValueError, KeyError, TypeError) as error:
            return web.json_response({'status': 'refused', 'reason': str(error)[:100]}, status=409)
    app.router.add_post('/meu/projects', handle)
