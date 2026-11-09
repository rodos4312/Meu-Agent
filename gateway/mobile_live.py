"""Pinned pairing transport for the existing single-writer conversation authority.

No legacy dispatcher, secondary agent, or transcript writer lives here. Pairing
limits both RPC targets and outbound events to the granted conversation space.
"""
import asyncio
import json
from pathlib import Path

from aiohttp import WSMsgType, web

from gateway.session_controls import AuthorityConnection


_SESSION_METHODS = frozenset({
    'session.resume', 'session.info', 'session.history', 'session.detach',
    'session.events.since', 'session.interrupt', 'session.stats',
    'prompt.submit', 'prompt.receipt', 'prompt.cancel',
    'approval.respond', 'clarify.respond',
    'subagent.list', 'subagent.tail',
    'turn.status', 'session.close', 'config.set',
})
_GLOBAL_METHODS = frozenset({'ping', 'runtime.describe', 'client.capabilities', 'config.get', 'model.options', 'clarify.lock',
                             'gateway.capabilities'})
_LIST_METHODS = frozenset({'session.active_list', 'session.list'})
_CREATE_FIELDS = frozenset({'request_id', 'source', 'model', 'provider', 'reasoning', 'toolsets',
                            'service_tier', 'follow_profile_config'})


class LiveScope:
    def __init__(self, preview):
        self.preview = preview

    @property
    def replay_epoch(self):
        authority = self.preview.authority
        return f'meu-live:{authority.instance_id}:{authority.epoch}'

    def check(self):
        preview = self.preview
        if preview.loop.time() >= preview.deadline or getattr(preview.authority, 'retiring', False):
            raise PermissionError('Pairing closed')
        if preview.personal_devices:
            preview.personal_devices.scope(preview.authority.profile_id, preview.device_id)

    def owns(self, session_id):
        from hermes_state_meu_sync import sync_snapshot

        if not isinstance(session_id, str):
            return False
        db = self.preview.authority.db
        with sync_snapshot(db) as conn:
            return self._owns_in(conn, session_id)

    def _owns_in(self, conn, session_id):
        db = self.preview.authority.db
        row = conn.execute(f'SELECT ({db._MEU_SYNC_PROFILE_SCOPE}) FROM sessions WHERE id = ?', (session_id,)).fetchone()
        if not row or not row[0]:
            return False
        if self.preview.personal_space:
            try:
                db._meu_require_space(conn, session_id, self.preview.personal_space)
            except LookupError:
                return False
        return True

    def read_live(self, session_id):
        """A consistent read while the owner works, never an importable settled receipt."""
        from hermes_state_meu_sync import sync_snapshot
        self.check()
        db = self.preview.authority.db
        with sync_snapshot(db) as conn:
            if not self._owns_in(conn, session_id):
                raise LookupError('Session outside pairing scope')
            messages = db._meu_sync_text(conn, session_id)
        db._validate_meu_sync_text(messages)
        return {'id': session_id, 'messages': messages}

    def create_params(self, params):
        if set(params) - _CREATE_FIELDS or params.get('source', 'gui') != 'gui':
            raise PermissionError('Unsupported mobile launch')
        params = dict(params, source='gui')
        if self.preview.personal_devices:
            from hermes_cli.meu_transfer_spaces import SpaceTransferFolder
            folder, _generation = SpaceTransferFolder(
                self.preview.authority, self.preview.personal_devices, self.preview.device_id).grant()
            params['cwd'] = str(folder)
        return params

    def mark_created(self, result):
        sid = result.get('session_id')
        if sid and self.preview.personal_space:
            self.preview.authority.db.set_meta('meu.space.session:' + sid, self.preview.personal_space)


class LiveConnection(AuthorityConnection):
    def __init__(self, preview, transport, channel):
        from gateway.owner_identity import host_owner_subject

        self.mobile_scope = LiveScope(preview)
        self.mobile_channel = channel
        self.model_confirmations = {}
        authority = preview.authority
        # Space-derived identity keeps retried creation IDs independent between users.
        subject = host_owner_subject() + ':meu:' + (preview.personal_space or 'owner')
        identity = {'user_id': subject, 'provider': 'local', 'profile_id': authority.profile_id,
                    'instance_id': authority.instance_id}
        # This gate grants access to pre-existing PC chats, after the explicit scope
        # check below. The caller cannot request an operator grant or another profile.
        super().__init__(authority, transport, identity, operator=True)

    async def dispatch(self, request):
        from fastapi import HTTPException

        try:
            await asyncio.to_thread(self.mobile_scope.check)
            return await self._scoped_dispatch(request)
        except (PermissionError, HTTPException):
            return {'jsonrpc': '2.0', 'id': request.get('id') if isinstance(request, dict) else None,
                    'error': {'code': 4003, 'message': 'Mobile pairing does not grant this operation'}}

    async def _scoped_dispatch(self, request):
        from gateway.mobile_live_protocol import request_params
        if not isinstance(request, dict):
            raise PermissionError('Invalid request')
        method, params = request.get('method'), request.get('params') or {}
        from hermes_cli.profiles import profile_matches_home
        if not isinstance(params, dict):
            raise PermissionError('Invalid parameters')
        profile = params.get('profile')
        if profile is not None and (not isinstance(profile, str)
                or not profile_matches_home(profile, Path(self.authority.profile_id))):
            raise PermissionError('Foreign profile')
        # Responses can only settle requests this transport was actually offered.
        if method is None:
            return await super().dispatch(request)
        if method == 'gateway.ping':
            return await super().dispatch(dict(request, method='ping'))
        if method == 'gateway.capabilities':
            return {'jsonrpc': '2.0', 'id': request.get('id'),
                    'result': {'per_session_exclusive_submit': True, 'meu_live_chat': 1}}
        if method == 'client.capabilities':
            return {'jsonrpc': '2.0', 'id': request.get('id'), 'result': {}}
        params = request_params(method, params)
        request = dict(request, params=params)
        if method == 'session.create':
            return await self._create_scoped(request, params)
        if method in _LIST_METHODS:
            response = await super().dispatch(request)
            if isinstance(response, dict) and 'result' in response:
                response['result']['sessions'] = [row for row in response['result']['sessions']
                    if await asyncio.to_thread(self.mobile_scope.owns, row.get('session_id', row.get('id')))]
            return response
        sid = params.get('session_id')
        if method in _SESSION_METHODS or (method in _GLOBAL_METHODS and sid is not None):
            if not await asyncio.to_thread(self.mobile_scope.owns, sid):
                raise PermissionError('Foreign session')
        elif method not in _GLOBAL_METHODS:
            raise PermissionError('Unsupported method')
        return await self._dispatch_owned(request, method, params)

    async def _create_scoped(self, request, params):
        from gateway.mobile_live_protocol import snapshot_projection
        params = self.mobile_scope.create_params(params)
        response = await super().dispatch(dict(request, params=params))
        if isinstance(response, dict) and isinstance(response.get('result'), dict):
            await asyncio.to_thread(self.mobile_scope.mark_created, response['result'])
            response['result'] = snapshot_projection(response['result'])
            response['result']['replay_epoch'] = self.mobile_scope.replay_epoch
        return response

    async def _dispatch_owned(self, request, method, params):
        from gateway.mobile_live_protocol import admission_projection, find_turn
        if method in {'session.close', 'session.interrupt', 'config.set'}:
            return await self._control_owned(request, method, params)
        if method == 'session.events.since':
            live = self.authority.sessions.get(params['session_id'])
            params = dict(params)
            supplied = params.get('replay_epoch')
            if live and supplied in (None, self.mobile_scope.replay_epoch):
                params['replay_epoch'] = live.event_stream.epoch
            request = dict(request, params=params)
        if method == 'prompt.submit':
            # The receipt's duplicate projection must be atomic across mobile
            # sockets too. Execution/idempotency itself stays in the authority.
            lock = self.authority.__dict__.setdefault('_meu_live_submit_lock', asyncio.Lock())
            async with lock:
                before = await find_turn(self, params)
                response = await super().dispatch(request)
                return self._project_reply(response, method, params, before)
        if method == 'turn.status':
            before = await find_turn(self, params)
            return {'jsonrpc': '2.0', 'id': request.get('id'), 'result': (
                admission_projection(before, params['client_turn_id']) if before else
                {'known': False, 'client_turn_id': params.get('client_turn_id')})}
        response = await super().dispatch(request)
        return self._project_reply(response, method, params, None)

    async def _control_owned(self, request, method, params):
        from gateway.session_contract import SessionRef
        if method == 'session.close':
            subscription = self.subscriptions.get(params['session_id'])
            if subscription:
                await self.detach(None, {'session_id': params['session_id'], 'subscription_id': subscription})
            return {'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'closed': bool(subscription)}}
        if method == 'session.interrupt':
            ref = SessionRef(self.actor.profile_id, params['session_id'])
            params = dict(params)
            params.setdefault('execution_generation', self.authority._handle(ref).execution_generation)
            return await super().dispatch(dict(request, params=params))
        from gateway.mobile_live_protocol import session_config_mutation
        if params.get('key') == 'fast' and set(params) == {'session_id', 'key', 'value'}:
            return await super().dispatch(request)
        selection = (params['session_id'], params.get('value'))
        mutation = session_config_mutation(self, params, self.model_confirmations.get(selection))
        response = await super().dispatch(dict(request, method='session.mutate', params=mutation))
        if isinstance(response, dict) and 'result' in response:
            if response['result'].get('confirm_required') is True:
                self.model_confirmations[selection] = response['result']['confirm']
            else:
                self.model_confirmations.pop(selection, None)
            response['result'] = {**response['result'], 'key': params['key'],
                                  'value': params['value'], 'scope': 'session'}
        return response

    def _project_reply(self, response, method, params, before):
        from gateway.mobile_live_protocol import admission_projection, snapshot_projection
        if isinstance(response, dict) and isinstance(response.get('result'), dict):
            if method == 'prompt.submit':
                response['result'] = {**response['result'], **admission_projection(
                    response['result'], params.get('input_id') or params['submission_id'], duplicate=before is not None)}
            elif method == 'session.resume':
                response['result'] = snapshot_projection(response['result'])
            if method in {'session.resume', 'session.events.since'}:
                response['result']['replay_epoch'] = self.mobile_scope.replay_epoch
            if method == 'session.events.since':
                response['result']['events'] = [self.mobile_channel.project_event(event)
                    for event in response['result'].get('events', [])]
        return response


class _Socket:
    def __init__(self, socket, scope):
        self.socket, self.scope = socket, scope
        self.subject = None
        self.turns = {}

    def project_event(self, params):
        from hermes_state_runtime import get_session_admission
        admission = params.get('admission_id')
        payload = dict(params.get('payload') or {})
        if admission:
            if admission not in self.turns:
                row = get_session_admission(self.scope.preview.authority.db, admission_id=admission)
                if len(self.turns) >= 128:
                    self.turns.pop(next(iter(self.turns)))
                self.turns[admission] = (row['request_id'] if row and row['principal_id'] == self.subject
                    and row['target_session_id'] == params.get('session_id') else None)
            payload['server_turn_id'] = admission
            if self.turns[admission]:
                payload['client_turn_id'] = self.turns[admission]
        return dict(params, payload=payload, replay_epoch=self.scope.replay_epoch)

    async def send_text(self, raw):
        self.scope.check()
        frames = []
        for line in raw.splitlines():
            frame = json.loads(line)
            if frame.get('method'):
                params = frame.get('params') or {}
                sid = params.get('session_id')
                if sid:
                    if not self.scope.owns(sid):
                        continue
                elif frame['method'] == 'event':
                    if params.get('type') not in {'gateway.ready', 'heartbeat'}:
                        continue
                else:
                    continue
                if frame['method'] == 'event' and params.get('session_id'):
                    frame['params'] = self.project_event(params)
            frames.append(json.dumps(frame, ensure_ascii=False))
            if (frame.get('method') == 'event' and frame['params'].get('session_id')
                    and frame['params'].get('type') in {'message.start', 'message.complete'}):
                # Existing renderers reconcile durable user rows on this signal,
                # including input submitted from the other connected device.
                frames.append(json.dumps({'jsonrpc': '2.0', 'method': 'event',
                    'params': {'type': 'sessions.changed', 'payload': {}}}))
        for frame in frames:
            self.scope.check()
            await self.socket.send_str(frame)

    async def close(self, code=1000, reason=''):
        await self.socket.close(code=code, message=reason.encode('utf-8'))


async def serve(preview, request):
    """The preview HTTP middleware has already checked TLS origin and bearer grant."""
    from tui_gateway.ws import WSTransport

    socket = web.WebSocketResponse(heartbeat=20, max_msg_size=256 * 1024)
    await socket.prepare(request)
    preview.live_sockets.add(socket)
    channel = _Socket(socket, LiveScope(preview))
    transport = WSTransport(channel, asyncio.get_running_loop())
    connection = LiveConnection(preview, transport, channel)
    channel.subject = connection.actor.subject
    try:
        ready = await transport.write_async({'jsonrpc': '2.0', 'method': 'event', 'params': {
            'type': 'gateway.ready', 'payload': {'session_authority': True, 'change_events': False,
                                               'heartbeat': True, 'meu_live_chat': 1,
                                               'replay_epoch': connection.mobile_scope.replay_epoch}}})
        if not ready:
            await socket.close()
            return socket
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                break
            for line in message.data.splitlines():
                try:
                    reply = await connection.dispatch(json.loads(line))
                except (ValueError, TypeError):
                    reply = {'jsonrpc': '2.0', 'id': None,
                             'error': {'code': -32700, 'message': 'Invalid JSON-RPC frame'}}
                if reply is not None and not await transport.write_async(reply):
                    await socket.close()
                    break
    finally:
        preview.live_sockets.discard(socket)
        await connection.close()
        transport.close()
    return socket


async def readiness(preview, request):
    """Prefix proof for an idle phone joining an already-running PC conversation."""
    try:
        history = await asyncio.to_thread(LiveScope(preview).read_live, request.match_info['session_id'])
    except LookupError:
        raise web.HTTPNotFound() from None
    except ValueError:
        raise web.HTTPBadRequest() from None
    return web.json_response({'live_view': history})
