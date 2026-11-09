"""Adopt an existing owner credential without rewriting conversations or files."""
import json

from fastapi import HTTPException


def migrate_owner(service, authority, expected, *, name=None, label=None):
    from gateway.mobile_preview import PROFILE_PAIRING_KEY

    def commit(conn):
        data = service._read(conn)
        previous = next((d for d in data['devices'].values()
                         if d['profile'] == authority.profile_id and d.get('migrated_legacy')), None)
        row = conn.execute('SELECT value FROM state_meta WHERE key = ?', (PROFILE_PAIRING_KEY,)).fetchone()
        raw = row[0] if row else None
        if not raw:
            if previous:
                return dict(previous), dict(data['spaces'][previous['space_id']])
            raise HTTPException(409, 'The existing connection is not available for migration.')
        record = json.loads(raw)
        if record != expected or record.get('profile') != authority.profile_id:
            raise HTTPException(409, 'The existing connection changed. Refresh before migrating.')
        space = service.owner_space(data, authority, name)
        device = service.new_device(data, authority, space, label)
        device.update(pairing=record, migrated_legacy=True)
        service._save(data, conn)
        service.store.set_meta(PROFILE_PAIRING_KEY, '', cursor=conn)
        return dict(device), dict(space)

    with service.lock:
        return service.store._execute_write(commit)
