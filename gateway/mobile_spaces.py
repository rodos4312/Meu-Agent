"""Owner-managed names and individually revocable phone credentials. No account server."""
from __future__ import annotations

from datetime import UTC, datetime
import json
import threading
import unicodedata
import uuid

from fastapi import HTTPException

from hermes_cli.meu_transfer_spaces import create_space_folder, space_root
from hermes_cli.meu_transfers import filename

KEY = 'meu.personal-devices.v1'
MAX_DEVICES = 32


def space_name(value):
    if not isinstance(value, str):
        raise HTTPException(400, 'Enter a name or nickname.')
    name = unicodedata.normalize('NFC', value.strip())
    if not name or len(name) > 80 or any(unicodedata.category(c).startswith('C') for c in name):
        raise HTTPException(400, 'Use a name or nickname of up to 80 characters.')
    return filename(name)


class PersonalDevices:
    """One service per gateway; all read-modify-write operations share this lock.

    Stored TLS identities and token digests stay in the existing protected local
    state store. Public projections never contain them or pairing challenges.
    """
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def _read(self):
        raw = self.store.get_meta(KEY)
        data = json.loads(raw) if raw else {'spaces': {}, 'devices': {}}
        if not isinstance(data, dict) or not isinstance(data.get('spaces'), dict) or not isinstance(data.get('devices'), dict):
            raise HTTPException(503, 'The device list could not be read. Existing data was kept.')
        return data

    def _save(self, data):
        self.store.set_meta(KEY, json.dumps(data, ensure_ascii=True))

    def add(self, authority, *, name=None, space_id=None, label=None):
        label = space_name(label) if label else None
        with self.lock:
            data = self._read()
            if len(data['devices']) >= MAX_DEVICES:
                raise HTTPException(409, 'Remove an unused device before adding another.')
            if space_id:
                space = data['spaces'].get(space_id)
                if not space or space['profile'] != authority.profile_id:
                    raise HTTPException(404, 'Personal space not found.')
                space_root(authority, space)
            else:
                name = space_name(name)
                if any(s['profile'] == authority.profile_id and s['name'].casefold() == name.casefold()
                       for s in data['spaces'].values()):
                    raise HTTPException(409, 'This name already has a space. Select it from the list.')
                binding = create_space_folder(authority, name)
                space_id = uuid.uuid4().hex
                space = {'id': space_id, 'profile': authority.profile_id, 'name': name, **binding}
                data['spaces'][space_id] = space
                # Keep the new space even if enrolment is later cancelled.
                self._save(data)
            device_id = uuid.uuid4().hex
            device = {'id': device_id, 'space_id': space_id, 'profile': authority.profile_id,
                      'label': label or space['name'],
                      'created_at': datetime.now(UTC).isoformat(), 'last_contact': None}
            data['devices'][device_id] = device
            self._save(data)
            return dict(device), dict(space)

    def scope(self, profile, device_id):
        with self.lock:
            data = self._read()
            device = data['devices'].get(device_id)
            if not device or device['profile'] != profile:
                raise HTTPException(410, 'This device was disconnected on the PC.')
            return dict(device), dict(data['spaces'][device['space_id']])

    def paired(self, profile, device_id, record):
        with self.lock:
            self.scope(profile, device_id)
            data = self._read()
            data['devices'][device_id]['pairing'] = record
            self._save(data)

    def contact(self, profile, device_id, timestamp):
        with self.lock:
            self.scope(profile, device_id)
            data = self._read()
            device = data['devices'][device_id]
            previous = device['last_contact']
            if previous is None or (datetime.fromisoformat(timestamp) - datetime.fromisoformat(previous)).total_seconds() >= 30:
                device['last_contact'] = timestamp
                self._save(data)

    def revoke(self, profile, device_id):
        with self.lock:
            self.scope(profile, device_id)
            data = self._read()
            del data['devices'][device_id]
            self._save(data)

    def saved(self):
        with self.lock:
            return [dict(d) for d in self._read()['devices'].values() if d.get('pairing')]

    def public(self, profile):
        with self.lock:
            data = self._read()
            return {
                'spaces': [{'id': s['id'], 'name': s['name']} for s in data['spaces'].values() if s['profile'] == profile],
                'devices': [{key: d[key] for key in ('id', 'space_id', 'label', 'created_at', 'last_contact')}
                            | {'paired': bool(d.get('pairing'))}
                            for d in data['devices'].values() if d['profile'] == profile],
            }
