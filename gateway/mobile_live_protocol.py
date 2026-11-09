"""Android Desktop-wire projection onto canonical durable admissions.

This adapter changes envelopes only. The authority still owns creation, FIFO,
execution and replay; compatibility must never invoke the legacy turn runner.
"""
import asyncio
import re
import uuid

from hermes_state_runtime import find_session_admission


def request_params(method, params):
    params = dict(params)
    params.pop('profile', None)  # The pairing already pins the profile.
    if method == 'session.create':
        if params.get('source') == 'desktop':
            params['source'] = 'gui'
        if params.pop('close_on_disconnect', False) is not False:
            raise PermissionError('Shared work survives viewer disconnect')
        if 'reasoning_effort' in params:
            params['reasoning'] = params.pop('reasoning_effort')
        if 'fast' in params:
            fast = params.pop('fast')
            if type(fast) is not bool:
                raise PermissionError('Invalid fast setting')
            params['service_tier'] = 'priority' if fast else 'normal'
    if method == 'session.resume':
        if any(key in params for key in ('title', 'latest', 'workspace', 'api_key', 'editor')):
            raise PermissionError('An exact shared session is required')
        params['display_projection'] = True
        params.pop('source', None)
    if method == 'prompt.submit' and 'client_turn_id' in params:
        params['input_id'] = params.pop('client_turn_id')
    if method == 'prompt.submit' and not (params.get('input_id') or params.get('submission_id')):
        # Legacy one-shot/voice sends have no durable retry identity. Admit once;
        # never infer that a lost response permits replaying the tool work.
        params['input_id'] = 'meu-live:' + uuid.uuid4().hex
    return params


def admission_projection(row, client_turn_id, *, duplicate=False):
    return {'accepted': True, 'known': True, 'client_turn_id': client_turn_id,
            'server_turn_id': row['admission_id'], 'duplicate': duplicate,
            'state': {'queued': 'accepted', 'started': 'running',
                      'terminal': 'terminal', 'unknown': 'unknown'}[row['status']]}


async def find_turn(connection, params):
    return await asyncio.to_thread(find_session_admission, connection.authority.db,
        principal_id=connection.actor.subject, session_id=params.get('session_id'),
        request_id=params.get('client_turn_id') or params.get('input_id') or params.get('submission_id'))


def snapshot_projection(result):
    if 'display_messages' in result:
        result = dict(result, messages=result['display_messages'])
    return result


def session_config_mutation(connection, params, confirm=None):
    """Composer choices affect this conversation, never the PC's global defaults."""
    from gateway.session_contract import SessionRef

    if set(params) - {'session_id', 'key', 'value', 'confirm_expensive_model'}:
        raise PermissionError('Unsupported session setting')
    key, value = params.get('key'), params.get('value')
    if key == 'model' and isinstance(value, str):
        match = re.fullmatch(r'(\S+) --provider ([\w-]+) --session', value)
        if not match:
            raise PermissionError('An explicit session model is required')
        payload = {'model': match[1], 'provider': match[2]}
        if params.get('confirm_expensive_model') is True and confirm:
            payload['confirm'] = confirm
    elif key == 'reasoning' and isinstance(value, str):
        payload = {'effort': value}
    else:
        raise PermissionError('Unsupported session setting')
    handle = connection.authority._handle(SessionRef(connection.actor.profile_id, params['session_id']))
    return {'session_id': params['session_id'], 'request_id': 'meu-setting:' + uuid.uuid4().hex,
            'expected_revision': handle.revision, 'expected_generation': handle.execution_generation,
            'operation': key, 'payload': payload}
