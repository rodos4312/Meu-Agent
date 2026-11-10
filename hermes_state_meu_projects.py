"""Durable single-owner project handoff over an already authenticated pairing.

Ownership never expires: a network partition cannot start a second executor.
Files are staged before surrender; an interrupted activation stays fenced and retryable.
"""
from __future__ import annotations

import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import uuid

from hermes_state_meu_sync import require_quiet
from hermes_state_errors import SessionActiveWriteGuardError
from hermes_state_runtime import RuntimeStoreError
from meu_project_files import CHUNK, checked_root, fingerprint, manifest, portable, regular, validate

PREFIX = 'meu.project.v1:'


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise ValueError('invalid_project_identity')
    return value


class ProjectStore:
    def __init__(self, db, local='pc', space=None):
        self.db, self.local, self.space = db, identity(local), space
        self.storage = Path(db.db_path).parent / 'meu-project-sync'

    def _records(self, conn):
        return [json.loads(row[0]) for row in conn.execute(
            'SELECT value FROM state_meta WHERE key LIKE ?', (PREFIX + '%',))]

    def _get(self, conn, pid):
        identity(pid)
        row = conn.execute('SELECT value FROM state_meta WHERE key=?', (PREFIX + pid,)).fetchone()
        if row is None:
            raise LookupError('project_unavailable')
        value = json.loads(row[0])
        if value['space'] != self.space:
            raise LookupError('project_unavailable')
        return value

    def _save(self, conn, value):
        conn.execute('INSERT OR REPLACE INTO state_meta(key,value) VALUES(?,?)',
                     (PREFIX + value['id'], json.dumps(value, separators=(',', ':'))))

    def catalog(self):
        with self.db._read_ctx() as conn:
            return {'projects': [self.public(item) for item in self._records(conn) if item['space'] == self.space]}

    @staticmethod
    def public(item):
        return {**{key: item[key] for key in ('id', 'name', 'owner', 'epoch', 'phase', 'sessions')},
                'return_requested': item.get('return_requested', False)}

    def request_return(self, pid):
        def write(conn):
            item = self._get(conn, pid)
            if self.local != 'pc' or item['owner'] == self.local:
                raise ValueError('project_already_local')
            item['return_requested'] = True
            self._save(conn, item)
            return self.public(item)
        return self.db._execute_write(write)

    def _quiet(self, conn, item):
        root = Path(item['root'])
        sessions = set(item['sessions'])
        conversations = {self.db._session_turn_lease_key_on_conn(conn, sid) for sid in sessions}
        for row in conn.execute('SELECT id,cwd FROM sessions'):
            # A compressed continuation may still carry the other device's cwd.
            # Its queued/unknown workers remain part of this project's handoff.
            if (self.db._session_turn_lease_key_on_conn(conn, row['id']) in conversations or
                    row['cwd'] and Path(row['cwd']).is_relative_to(root)):
                sessions.add(row['id'])
        for sid in sessions:
            require_quiet(self.db, conn, sid)

    def _unchanged_replica(self, item):
        if item.get('baseline') is not None and fingerprint(manifest(item['root'])) != item['baseline']:
            raise ValueError('local_project_changes')

    def register(self, root, name, sessions, *, pid=None, owner=None):
        root = checked_root(root)
        home = Path(self.db.db_path).parent.absolute()
        if root == home or home.is_relative_to(root) or root.is_relative_to(home):
            raise ValueError('select_project_not_engine_directory')
        portable(name)
        if '/' in name or not isinstance(sessions, list) or not 1 <= len(sessions) <= 100:
            raise ValueError('select_project_conversation')
        pid = identity(pid or uuid.uuid4().hex)
        def write(conn):
            for sid in sessions:
                row = conn.execute(f'SELECT ({self.db._MEU_SYNC_PROFILE_SCOPE}) FROM sessions WHERE id=?', (sid,)).fetchone()
                if not row or not row[0]:
                    raise LookupError('conversation_unavailable')
                if self.space is not None:
                    self.db._meu_require_space(conn, sid, self.space)
            for item in self._records(conn):
                other = Path(item['root'])
                if item['id'] == pid or root.is_relative_to(other) or other.is_relative_to(root) or set(sessions) & set(item['sessions']):
                    raise ValueError('project_already_registered')
            item = {'id': pid, 'name': name, 'root': str(root), 'sessions': sessions,
                    'owner': owner or self.local, 'local': self.local, 'epoch': 0, 'phase': 'ready', 'space': self.space}
            self._quiet(conn, item)
            self._save(conn, item)
            return self.public(item)
        return self.db._execute_write(write)

    def prepare(self, pid, receiver, transfer):
        identity(receiver), identity(transfer)
        def write(conn):
            item = self._get(conn, pid)
            if item.get('cancelled_transfer') == transfer:
                raise ValueError('transfer_cancelled')
            if item.get('transfer') == transfer and item['phase'] in {'offered', 'released'}:
                if item['receiver'] != receiver:
                    raise ValueError('handoff_mismatch')
                return item['offer']
            if item['owner'] != self.local or item['phase'] != 'ready' or receiver == self.local:
                raise ValueError('project_owned_elsewhere')
            self._quiet(conn, item)
            snapshot = self.storage / pid / transfer / 'out'
            if snapshot.exists():
                # A killed snapshot worker never committed an offer, so no peer
                # can be reading this generated staging directory yet.
                import shutil
                checked_root(snapshot)
                shutil.rmtree(snapshot)
            snapshot.mkdir(parents=True, exist_ok=False)
            try:
                entries = manifest(item['root'], copy_to=snapshot)
            except Exception:
                # Only this newly created, generated staging directory can be removed.
                import shutil
                shutil.rmtree(snapshot)
                raise
            offer = {'id': pid, 'name': item['name'], 'sessions': item['sessions'], 'transfer': transfer,
                     'epoch': item['epoch'] + 1, 'sender': self.local, 'receiver': receiver,
                     'files': entries, 'digest': fingerprint(entries)}
            item.update(phase='offered', transfer=transfer, receiver=receiver, offer=offer)
            self._save(conn, item)
            return offer
        return self.db._execute_write(write)

    def chunk(self, pid, transfer, path, offset):
        portable(path)
        with self.db._read_ctx() as conn:
            item = self._get(conn, pid)
            if item.get('transfer') != transfer or item['phase'] not in {'offered', 'released'}:
                raise ValueError('handoff_mismatch')
            entry = next((entry for entry in item['offer']['files'] if entry['path'] == path), None)
            if not entry or type(offset) is not int or not 0 <= offset <= entry['size']:
                raise ValueError('invalid_project_chunk')
            if entry['directory']:
                return {'data': ''}
            file = self.storage / pid / transfer / 'out' / path
            regular(file)
            with file.open('rb') as stream:
                stream.seek(offset)
                return {'data': base64.b64encode(stream.read(CHUNK)).decode('ascii')}

    def receive(self, offer, root):
        if not isinstance(offer, dict) or set(offer) != {'id', 'name', 'sessions', 'transfer', 'epoch', 'sender', 'receiver', 'files', 'digest'}:
            raise ValueError('invalid_project_offer')
        for field in ('id', 'transfer', 'sender', 'receiver'):
            identity(offer[field])
        portable(offer['name'])
        validate(offer['files'])
        if (offer['receiver'] != self.local or offer['sender'] == self.local or
                type(offer['epoch']) is not int or offer['epoch'] < 1 or fingerprint(offer['files']) != offer['digest']):
            raise ValueError('invalid_project_offer')
        root = checked_root(root)
        pid, transfer = offer['id'], offer['transfer']
        with self.db._read_ctx() as conn:
            existing = next((item for item in self._records(conn) if item['id'] == pid), None)
        if existing is None:
            # Register an empty replica as remote-owned, never executable before activation.
            if any(root.iterdir()):
                raise ValueError('project_destination_not_empty')
            self.register(root, offer['name'], offer['sessions'], pid=pid, owner=offer['sender'])
        def write(conn):
            item = self._get(conn, pid)
            if item.get('transfer') == transfer and item['phase'] == 'receiving':
                if item['offer'] != offer:
                    raise ValueError('handoff_mismatch')
                return {'status': 'receiving'}
            if (item['owner'] != offer['sender'] or item['phase'] not in {'ready', 'released'} or
                    item['epoch'] >= offer['epoch'] or set(item['sessions']) != set(offer['sessions'])):
                raise ValueError('stale_project_offer')
            self._quiet(conn, item)
            self._unchanged_replica(item)
            stage = Path(item['root']).with_name('.meu-in-' + pid + '-' + transfer)
            stage.mkdir(parents=True, exist_ok=True)
            item.update(phase='receiving', transfer=transfer, offer=offer)
            self._save(conn, item)
            return {'status': 'receiving'}
        return self.db._execute_write(write)

    def put_chunk(self, pid, transfer, path, offset, data):
        portable(path)
        if not isinstance(data, str) or len(data) > CHUNK * 2:
            raise ValueError('invalid_project_chunk')
        payload = base64.b64decode(data, validate=True)
        if len(payload) > CHUNK or type(offset) is not int or offset < 0:
            raise ValueError('invalid_project_chunk')
        def write(conn):
            item = self._get(conn, pid)
            if item['phase'] != 'receiving' or item['transfer'] != transfer:
                raise ValueError('handoff_mismatch')
            entry = next((entry for entry in item['offer']['files'] if entry['path'] == path), None)
            if not entry or offset + len(payload) > entry['size']:
                raise ValueError('invalid_project_chunk')
            destination = Path(item['root']).with_name('.meu-in-' + pid + '-' + transfer) / path
            if entry['directory']:
                destination.mkdir(parents=True, exist_ok=True)
                return {'status': 'stored'}
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('r+b' if destination.exists() else 'xb') as stream:
                stream.seek(0, 2)
                if offset > stream.tell():
                    raise ValueError('missing_project_chunk')
                stream.seek(offset)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if entry['executable']:
                destination.chmod(0o700)
            return {'status': 'stored'}
        return self.db._execute_write(write)

    def verify(self, pid, transfer):
        with self.db._read_ctx() as conn:
            item = self._get(conn, pid)
            if item['phase'] != 'receiving' or item['transfer'] != transfer:
                raise ValueError('handoff_mismatch')
            actual = manifest(Path(item['root']).with_name('.meu-in-' + pid + '-' + transfer))
            # Executable bits are platform-specific; content and sizes must match exactly.
            return {'digest': _content_digest(actual, item['offer']['files'])}

    def release(self, pid, transfer):
        def write(conn):
            item = self._get(conn, pid)
            if item.get('transfer') != transfer or item['phase'] not in {'offered', 'released'}:
                raise ValueError('handoff_mismatch')
            if item['phase'] == 'offered':
                self._quiet(conn, item)
                if fingerprint(manifest(item['root'])) != item['offer']['digest']:
                    raise ValueError('project_changed')
                item.update(owner=item['receiver'], epoch=item['offer']['epoch'], phase='released', baseline=item['offer']['digest'])
                self._save(conn, item)
            return {'transfer': transfer, 'id': pid, 'epoch': item['epoch'], 'digest': item['offer']['digest'],
                    'owner': item['owner']}
        return self.db._execute_write(write)

    def activate(self, grant):
        def write(conn):
            item = self._get(conn, grant['id'])
            if item.get('last_grant') == grant and item['phase'] == 'ready':
                return self.public(item)
            if item['phase'] != 'receiving':
                raise ValueError('handoff_mismatch')
            offer = item['offer']
            expected = {'transfer': item['transfer'], 'id': item['id'], 'epoch': offer['epoch'],
                        'digest': offer['digest'], 'owner': self.local}
            if grant != expected:
                raise ValueError('invalid_project_grant')
            self._quiet(conn, item)
            root = Path(item['root'])
            stage = root.with_name('.meu-in-' + item['id'] + '-' + item['transfer'])
            backup = root.with_name('.meu-backup-' + item['id'] + '-' + item['transfer'])
            if stage.exists():
                _content_digest(manifest(stage), offer['files'])
                if root.exists():
                    checked_root(root)
                    self._unchanged_replica(item)
                if not backup.exists():
                    root.rename(backup)
                stage.rename(root)
            _retain_local_files(backup, root)
            # A restart after rename verifies the published tree before granting execution.
            _content_digest(manifest(root), offer['files'])
            item.update(owner=self.local, epoch=offer['epoch'], phase='ready', last_grant=grant,
                        baseline=fingerprint(manifest(root)), return_requested=False)
            self._save(conn, item)
            for sid in item['sessions']:
                conn.execute('UPDATE sessions SET cwd=? WHERE id=?', (str(root), sid))
            return self.public(item)
        return self.db._execute_write(write)

    def cancel_offer(self, pid, transfer):
        def write(conn):
            item = self._get(conn, pid)
            if item.get('cancelled_transfer') == transfer and item['phase'] == 'ready':
                return self.public(item)
            if item['phase'] == 'ready' and item['owner'] == self.local and item.get('transfer') != transfer:
                item['cancelled_transfer'] = transfer
                self._save(conn, item)
                return self.public(item)
            if item['phase'] != 'offered' or item.get('transfer') != transfer or item['owner'] != self.local:
                raise ValueError('handoff_already_released')
            item.update(phase='ready', cancelled_transfer=transfer)
            self._save(conn, item)
            return self.public(item)
        return self.db._execute_write(write)


    def discard_receive(self, pid, transfer):
        def write(conn):
            item = self._get(conn, pid)
            if item.get('discarded_transfer') == transfer:
                return self.public(item)
            if item['phase'] != 'receiving' or item['transfer'] != transfer or item['owner'] == self.local:
                raise ValueError('handoff_mismatch')
            item.update(phase='ready', discarded_transfer=transfer)
            self._save(conn, item)
            return self.public(item)
        return self.db._execute_write(write)


def _content_digest(actual, expected):
    stripped = lambda items: [{key: item[key] for key in ('path', 'size', 'sha256', 'directory')} for item in items]
    if stripped(actual) != stripped(expected):
        raise ValueError('incomplete_project')
    return fingerprint(expected)


def _retain_local_files(backup, root):
    """Keep excluded local credentials/VCS on their own device, never on the wire."""
    if not backup.exists():
        return
    for directory, folders, files in os.walk(backup, followlinks=False):
        for name in [*folders, *files]:
            source = Path(directory) / name
            relative = source.relative_to(backup).as_posix()
            try:
                portable(relative)
            except ValueError as error:
                if str(error) != 'private_or_generated_file':
                    raise
                regular(source)
                target = root / relative
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source.rename(target)
                if name in folders:
                    folders.remove(name)


def project_for_session(db, conn, sid):
    logical = db._session_turn_lease_key_on_conn(conn, sid)
    row = conn.execute('SELECT cwd FROM sessions WHERE id=?', (sid,)).fetchone()
    for item in ProjectStore(db)._records(conn):
        if sid in item['sessions'] or logical in item['sessions'] or (row and row[0] and Path(row[0]).is_relative_to(Path(item['root']))):
            return item
    return None


def require_project_execution(db, conn, sid):
    item = project_for_session(db, conn, sid)
    if item and (item['phase'] != 'ready' or item['owner'] != item.get('local', 'pc')):
        raise RuntimeStoreError('session_busy', detail='Το έργο ανήκει στην άλλη συσκευή ή μεταφέρεται. Χρειάζεται ολοκληρωμένη παράδοση.')
    if item:
        logical = db._session_turn_lease_key_on_conn(conn, sid)
        for row in conn.execute('SELECT id,cwd FROM sessions'):
            other = row['id']
            if db._session_turn_lease_key_on_conn(conn, other) == logical:
                continue
            if other in item['sessions'] or (row['cwd'] and Path(row['cwd']).is_relative_to(Path(item['root']))):
                try:
                    require_quiet(db, conn, other)
                except SessionActiveWriteGuardError:
                    raise RuntimeStoreError('session_busy', detail='Ένας άλλος agent εργάζεται ήδη στο ίδιο έργο.') from None


def execution_policy(db, sid, policy):
    with db._read_ctx() as conn:
        item = project_for_session(db, conn, sid)
        if item is None:
            return policy
        require_project_execution(db, conn, sid)
    terminal = json.loads(policy.terminal_json)
    terminal['TERMINAL_CWD'] = item['root']
    terminal['TERMINAL_ENV'] = 'local'
    return replace(policy, cwd=item['root'], terminal_json=json.dumps(terminal))
