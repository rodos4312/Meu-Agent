"""Short-lived read-side mirrors. They never become model context or admissions."""
import json
import re
import time

from hermes_state_meu_sync import require_quiet, sync_snapshot
from hermes_state_errors import SessionActiveWriteGuardError

_PREFIX = 'meu.observation:'
_MAX_AGE = 90


def read_view(db, session_id):
    """Read committed visible text even while its execution owns the write lease."""
    with sync_snapshot(db) as conn:
        return _read_view_on(db, conn, session_id)


def _read_view_on(db, conn, session_id):
    if not isinstance(session_id, str) or not db._MEU_SYNC_SESSION_ID.fullmatch(session_id):
        raise ValueError('Invalid conversation')
    row = conn.execute(
        f'SELECT ({db._MEU_SYNC_PROFILE_SCOPE}) FROM sessions WHERE id = ?', (session_id,)).fetchone()
    if not row or not row[0]:
        raise LookupError('Conversation unavailable')
    messages = db._meu_sync_text(conn, session_id)
    busy = False
    try:
        require_quiet(db, conn, session_id)
    except SessionActiveWriteGuardError:
        busy = True
    db._validate_meu_sync_text(messages)
    return {'id': session_id, 'messages': messages, 'busy': busy, 'draft': ''}


def validate_view(db, view):
    if not isinstance(view, dict) or set(view) != {'id', 'messages', 'busy', 'draft'}:
        raise ValueError('Invalid observation')
    sid = view['id']
    if not isinstance(sid, str) or not db._MEU_SYNC_SESSION_ID.fullmatch(sid):
        raise ValueError('Invalid conversation')
    db._validate_meu_sync_text(view['messages'])
    if type(view['busy']) is not bool or not isinstance(view['draft'], str):
        raise ValueError('Invalid observation state')
    if len(view['draft'].encode('utf-8')) > 256 * 1024 or (view['draft'] and not view['busy']):
        raise ValueError('Invalid live draft')
    return sid


def observe(db, source, view, *, personal_space=None):
    """Store a display snapshot separately from every canonical message row."""
    sid = validate_view(db, view)
    if not isinstance(source, str) or not re.fullmatch(r'[a-z0-9-]{1,64}', source):
        raise ValueError('Invalid observation source')

    def write(conn):
        # Observation cannot resurrect a deleted chat or address another session type.
        row = conn.execute(
            f'SELECT ({db._MEU_SYNC_PROFILE_SCOPE}) FROM sessions WHERE id = ?', (sid,)).fetchone()
        if row is None:
            from hermes_state_mutation_retirement import retired_in
            if retired_in(conn, sid):
                raise LookupError('Conversation deleted')
            normalized = db._normalize_import_session({'source': 'gui'}, sid, view['messages'])
            db._import_session_row(conn, normalized['session'], normalized['messages'], sid)
            if personal_space is not None:
                conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?)', ('meu.space.session:' + sid, personal_space))
        elif not row[0]:
            raise LookupError('Conversation unavailable')
        if personal_space is not None:
            db._meu_require_space(conn, sid, personal_space)
        key = _PREFIX + sid + ':' + source
        conn.execute('INSERT OR REPLACE INTO state_meta(key,value) VALUES (?,?)', (
            key, json.dumps({'received_at': time.time(), 'view': view}, separators=(',', ':'))))
        conn.execute('DELETE FROM state_meta WHERE key LIKE ? AND '
                     'CAST(json_extract(value, \'$.received_at\') AS REAL) < ?',
                     (_PREFIX + '%', time.time() - _MAX_AGE))
        conn.execute('DELETE FROM state_meta WHERE key IN (SELECT key FROM state_meta WHERE key LIKE ? '
                     'ORDER BY CAST(json_extract(value, \'$.received_at\') AS REAL) DESC LIMIT -1 OFFSET 32)',
                     (_PREFIX + '%',))
    db._execute_write(write)


def _extension(local, remote):
    return len(remote) >= len(local) and all(left == right for left, right in zip(local, remote))


def remote_view(db, session_id):
    """Only an unambiguous strict extension may be painted over a local copy."""
    with sync_snapshot(db) as conn:
        local = _read_view_on(db, conn, session_id)
        return _remote_view_on(conn, local)


def _remote_view_on(conn, local):
    if local['busy']:
        return None
    prefix = _PREFIX + local['id'] + ':'
    rows = conn.execute('SELECT value FROM state_meta WHERE substr(key,1,?) = ?', (len(prefix), prefix))
    candidates = []
    for row in rows:
        saved = json.loads(row[0])
        view = saved['view']
        if time.time() - saved['received_at'] > _MAX_AGE:
            continue
        if _extension(local['messages'], view['messages']):
            candidates.append(view)
    if not candidates:
        return None
    longest = max(candidates, key=lambda item: (len(item['messages']), item['busy']))
    active_drafts = {item['draft'] for item in candidates if item['busy']}
    if (any(not _extension(item['messages'], longest['messages']) for item in candidates)
            or len(active_drafts) > 1):
        return {'id': local['id'], 'messages': local['messages'], 'busy': True,
                'draft': 'Οι συνδεδεμένες συσκευές έχουν διαφορετική συνέχεια. Τα ιστορικά διατηρούνται χωριστά.'}
    if len(longest['messages']) == len(local['messages']) and not longest['busy']:
        return None
    return longest


def display_observation(db, session_id):
    """Separate read model: no fabricated message IDs, editable rows or model history."""
    with sync_snapshot(db) as conn:
        local = _read_view_on(db, conn, session_id)
        view = _remote_view_on(conn, local)
    if view is None:
        return None
    return {**view, 'messages': view['messages'][len(local['messages']):]}


def require_local_execution(db, session_id, *, conn=None):
    """A mirrored draft is display authority, never permission to run a second agent."""
    try:
        pending = (remote_view(db, session_id) if conn is None
                   else _remote_view_on(conn, _read_view_on(db, conn, session_id)))
    except (LookupError, ValueError):
        return
    if pending is not None:
        from hermes_state_runtime import RuntimeStoreError
        raise RuntimeStoreError('session_busy', detail='This conversation is still updating from the paired device.')
