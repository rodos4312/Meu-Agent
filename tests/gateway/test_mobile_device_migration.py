"""Owner enrolment preserves the old credential, records and transfer paths."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from gateway.mobile_device_migration import migrate_owner
from gateway.mobile_preview import PROFILE_PAIRING_KEY
from gateway.mobile_spaces import PersonalDevices
from hermes_cli.meu_transfer_spaces import MobileTransferFolder, SpaceTransferFolder
from hermes_cli.meu_transfers import TransferFolder
from hermes_state import SessionDB


@pytest.fixture
def existing(tmp_path):
    with SessionDB(tmp_path / 'state.db') as db:
        authority = SimpleNamespace(db=db, profile_id=str(tmp_path), retiring=False, retired=False)
        service = PersonalDevices(db)
        root = tmp_path / 'kinito'
        root.mkdir()
        (root / 'project').mkdir()
        (root / 'project' / 'original.bin').write_bytes(bytes(range(256)))
        TransferFolder(authority).select(str(root))
        sid = 'local-' + 'a' * 64
        history = {'id': sid, 'messages': [{'role': 'user', 'content': 'existing conversation',
                                           'message_uid': 'b' * 32}]}
        db.apply_meu_sync_history(history, profile_sync=True)
        record = {'profile': authority.profile_id, 'digest': 'c' * 64, 'pem': 'stored private fixture',
                  'interfaces': ['192.168.1.2/24'], 'ports': [50878]}
        db.set_meta(PROFILE_PAIRING_KEY, json.dumps(record))
        yield authority, service, root, record, history


def test_migration_keeps_owner_history_files_and_transfer_identity(existing):
    authority, service, root, record, history = existing
    generation = TransferFolder(authority).listing()['root_id']
    service.add(authority, name='Separate user')
    device, space = migrate_owner(service, authority, record, name='Λάζαρος', label='Κινητό 1')
    assert space['owner'] is True
    assert service.saved()[0]['pairing'] == record
    assert not authority.db.get_meta(PROFILE_PAIRING_KEY)
    folder = SpaceTransferFolder(authority, service, device['id'])
    assert folder.grant(generation) == (root, generation)
    assert (root / 'project' / 'original.bin').read_bytes() == bytes(range(256))
    assert authority.db.export_meu_sync_history(history['id'], profile_sync=True)['messages'] == history['messages']
    other, same = service.add(authority, space_id=space['id'], label='Κινητό 2')
    assert same == space
    service.revoke(authority.profile_id, device['id'])
    assert SpaceTransferFolder(authority, service, other['id']).grant(generation) == (root, generation)
    with pytest.raises(HTTPException):
        folder.grant(generation)
    assert record['digest'] not in json.dumps(service.public(authority.profile_id))


def test_partial_metadata_failure_rolls_back_without_changing_data(existing, monkeypatch):
    authority, service, root, record, history = existing
    original = authority.db.set_meta

    def fail_retirement(key, value, **kwargs):
        if key == PROFILE_PAIRING_KEY:
            raise OSError('controlled interrupted commit')
        return original(key, value, **kwargs)

    monkeypatch.setattr(authority.db, 'set_meta', fail_retirement)
    with pytest.raises(OSError):
        migrate_owner(service, authority, record, name='Owner')
    assert service.public(authority.profile_id) == {'spaces': [], 'devices': []}
    assert json.loads(authority.db.get_meta(PROFILE_PAIRING_KEY)) == record
    assert authority.db.export_meu_sync_history(history['id'], profile_sync=True)['messages'] == history['messages']
    assert (root / 'project' / 'original.bin').read_bytes() == bytes(range(256))


def test_concurrent_retries_are_idempotent_and_cannot_revive_a_revoked_device(existing):
    authority, service, _root, record, _history = existing
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(migrate_owner, service, authority, record, name='Owner') for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    assert len(service.public(authority.profile_id)['devices']) == 1
    service.revoke(authority.profile_id, results[0][0]['id'])
    with pytest.raises(HTTPException):
        migrate_owner(service, authority, record, name='Owner')


def test_a_changed_credential_or_foreign_profile_is_not_adopted(existing):
    authority, service, _root, record, _history = existing
    for expected, owner in (({**record, 'digest': 'd' * 64}, authority),
                            (record, SimpleNamespace(profile_id='different-profile'))):
        with pytest.raises(HTTPException):
            migrate_owner(service, owner, expected, name='Owner')
    assert service.public(authority.profile_id) == {'spaces': [], 'devices': []}


def test_transfer_admitted_before_migration_still_observes_device_revocation(existing):
    authority, service, root, record, _history = existing
    preview = SimpleNamespace(authority=authority, personal_devices=None, device_id=None)
    folder = MobileTransferFolder(preview)
    writer = folder.upload('partial.bin', folder.listing()['root_id'])
    try:
        writer.write(b'before migration')
        device, _space = migrate_owner(service, authority, record, name='Owner')
        preview.personal_devices, preview.device_id = service, device['id']
        service.revoke(authority.profile_id, device['id'])
        with pytest.raises(HTTPException):
            writer.write(b'after revocation')
    finally:
        writer.close()
    assert not (root / 'partial.bin').exists()


def test_owner_migration_does_not_require_or_change_a_shared_folder(existing):
    from gateway.mobile_live import LiveScope
    from hermes_cli.meu_transfers import KEY

    authority, service, root, record, _history = existing
    authority.db.set_meta(KEY, '')
    device, _space = migrate_owner(service, authority, record, name='Owner')
    preview = SimpleNamespace(authority=authority, personal_devices=service,
                              device_id=device['id'], personal_space=None)
    assert LiveScope(preview).create_params({}) == {'source': 'gui'}
    assert SpaceTransferFolder(authority, service, device['id']).listing() == {'enabled': False}
    assert (root / 'project' / 'original.bin').read_bytes() == bytes(range(256))


@pytest.mark.parametrize('wifi,vpn', [(True, True), (True, False), (False, True), (False, False)])
def test_new_pairing_keeps_available_private_networks(monkeypatch, wifi, vpn):
    import gateway.mobile_preview as mobile
    from hermes_cli.web_routers.mobile_devices import device_networks

    def discover(available, address):
        if not available:
            raise ValueError('adapter unavailable')
        return ipaddress.IPv4Interface(address)

    monkeypatch.setattr(mobile, 'local_network', lambda: discover(wifi, '192.168.1.24/24'))
    monkeypatch.setattr(mobile, 'tailscale_network', lambda: discover(vpn, '100.64.1.2/32'))
    if not wifi and not vpn:
        with pytest.raises(HTTPException) as error:
            device_networks()
        assert error.value.status_code == 503
    else:
        expected = (['192.168.1.24/24'] if wifi else []) + (['100.64.1.2/32'] if vpn else [])
        assert [str(interface) for interface in device_networks()] == expected
