"""A single text-sync pairing works on both pinned private addresses."""

import asyncio
import base64
import ipaddress
import ssl
from types import SimpleNamespace

from aiohttp import ClientSession

from gateway.mobile_preview import MobilePreview


def test_sync_pairing_uses_both_interfaces():
    asyncio.run(_exercise_pairing())


async def _exercise_pairing():
    from hermes_state_errors import SessionActiveWriteGuardError

    session_id = "local-" + "a" * 64
    history = {"id": session_id, "messages": []}
    applied = []
    exporting_busy = False

    def export(requested_id):
        assert requested_id == session_id
        if exporting_busy:
            raise SessionActiveWriteGuardError("Active writer")
        return history

    def apply(snapshot):
        applied.append(snapshot)
        return "unchanged"

    authority = SimpleNamespace(db=SimpleNamespace(
        export_meu_sync_history=export,
        apply_meu_sync_history=apply,
    ))
    preview = MobilePreview(
        authority, ipaddress.IPv4Interface("127.0.0.1/8"),
        sync_session=session_id, sync_tailscale=ipaddress.IPv4Interface("127.0.0.2/8"),
    )
    await preview.start()
    try:
        version, *fields = preview.code.split(".")
        assert version == "meusync1"
        origins, challenge, cert = [base64.urlsafe_b64decode(field + "=" * (-len(field) % 4))
                                    for field in fields]
        lan, vpn = origins.decode().splitlines()
        assert lan.startswith("https://127.0.0.1:")
        assert vpn.startswith("https://127.0.0.2:")
        tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
        async with ClientSession() as client:
            async with client.get(vpn + "/meu/sync", ssl=tls) as response:
                assert response.status == 401
            async with client.post(lan + "/meu/pair", ssl=tls,
                                   json={"challenge": challenge.decode()}) as response:
                assert response.status == 200
                key = (await response.json())["key"]
            async with client.post(vpn + "/meu/pair", ssl=tls,
                                   json={"challenge": challenge.decode()}) as response:
                assert response.status == 401

            headers = {"Authorization": f"Bearer {key}"}
            exporting_busy = True
            async with client.get(vpn + "/meu/sync", ssl=tls, headers=headers) as response:
                assert response.status == 409
                assert await response.json() == {"status": "busy"}
            exporting_busy = False
            async with client.get(vpn + "/meu/sync", ssl=tls, headers=headers) as response:
                assert response.status == 200
                assert await response.json() == history
            async with client.put(vpn + "/meu/sync", ssl=tls, headers=headers,
                                  json={**history, "id": "another-session"}) as response:
                assert response.status == 403
            async with client.put(lan + "/meu/sync", ssl=tls, headers=headers,
                                  json=history) as response:
                assert response.status == 200
                assert await response.json() == {"status": "unchanged"}
            async with client.post(vpn + "/v1/runs", ssl=tls, headers=headers,
                                   json={"input": "must not run"}) as response:
                assert response.status == 404
        assert applied == [history]
    finally:
        await preview.close()


def test_profile_sync_requires_its_own_pairing_and_limits_session_scope(tmp_path):
    asyncio.run(_exercise_profile_pairing(tmp_path))


async def _exercise_profile_pairing(tmp_path):
    from hermes_state import SessionDB

    local_id, hidden_id, new_id = ("local-" + char * 64 for char in "abc")
    with SessionDB(tmp_path / "profile.db") as db:
        db.create_session(local_id, source="gui")
        db.create_session(hidden_id, source="telegram")
        db.append_message(local_id, "user", "Visible")
        db.append_message(hidden_id, "user", "Outside scope")
        preview = MobilePreview(
            SimpleNamespace(db=db), ipaddress.IPv4Interface("127.0.0.1/8"),
            sync_profile=True,
        )
        await preview.start()
        try:
            version, *fields = preview.code.split(".")
            assert version == "meusync2"
            origin, challenge, cert = [base64.urlsafe_b64decode(field + "=" * (-len(field) % 4))
                                        for field in fields]
            root = origin.decode() + "/meu/sync/sessions"
            tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
            async with ClientSession() as client:
                async with client.get(root, ssl=tls) as response:
                    assert response.status == 401
                async with client.post(origin.decode() + "/meu/pair", ssl=tls,
                                       json={"challenge": challenge.decode()}) as response:
                    assert response.status == 200
                    key = (await response.json())["key"]
                headers = {"Authorization": f"Bearer {key}"}
                async with client.get(root, ssl=tls, headers=headers) as response:
                    assert await response.json() == {"ids": [local_id], "next": None}
                async with client.get(root + "?timestamps=1", ssl=tls, headers=headers) as response:
                    assert (await response.json())["timestamps"] is True
                async with client.get(f"{root}/{local_id}", ssl=tls, headers=headers) as response:
                    message = (await response.json())["messages"][0]
                    assert message["content"] == "Visible" and "timestamp" not in message
                async with client.get(f"{root}/{local_id}?timestamps=1", ssl=tls, headers=headers) as response:
                    assert await response.json() == db.export_meu_sync_history(
                        local_id, profile_sync=True, timestamps=True)
                async with client.get(f"{root}/{hidden_id}", ssl=tls, headers=headers) as response:
                    assert response.status == 404
                history = {"id": hidden_id, "messages": []}
                async with client.put(f"{root}/{hidden_id}", ssl=tls, headers=headers,
                                      json=history) as response:
                    assert response.status == 404
                history = {"id": new_id, "messages": [
                    {"role": "user", "content": "New local chat", "message_uid": "a" * 32}]}
                async with client.put(f"{root}/{new_id}", ssl=tls, headers=headers,
                                      json=history) as response:
                    assert await response.json() == {"status": "created"}
                assert db.export_meu_sync_history(new_id, profile_sync=True) == history
                from hermes_state_meu_sync import fingerprint
                async with client.get(root + "?recovery=1", ssl=tls, headers=headers) as response:
                    assert (await response.json())["sync_recovery"] == 1
                async with client.get(f"{root}/{local_id}?recovery=1", ssl=tls, headers=headers) as response:
                    common = (await response.json())["history"]
                phone_history = {**common, "messages": [*common["messages"], {
                    "role": "user", "content": "Phone continuation while PC updates", "message_uid": "b" * 32}]}
                db.append_message(local_id, "assistant", "PC continuation")
                pc_history = db.export_meu_sync_history(local_id, profile_sync=True)
                resolution = {"pc": pc_history, "phone": phone_history,
                              "prefer": "phone", "expected": fingerprint(pc_history)}
                async with client.post(f"{root}/{local_id}/resolve", ssl=tls, headers=headers, json=resolution) as response:
                    assert response.status == 200
                    recovery = await response.json()
                    assert recovery["status"] == "resolved"
                async with client.get(f"{root}/{local_id}/backups/{recovery['receipt']}", ssl=tls, headers=headers) as response:
                    assert response.status == 200
                    saved = await response.json()
                    assert saved["pc"] == pc_history and saved["phone"] == phone_history
                async with client.get(origin.decode() + "/meu/sync/backups", ssl=tls, headers=headers) as response:
                    assert len((await response.json())["backups"]) == 1
                async with client.get(f"{root}/{hidden_id}/backups/{recovery['receipt']}", ssl=tls, headers=headers) as response:
                    assert response.status == 404
                async with client.post(origin.decode() + "/v1/runs", ssl=tls,
                                       headers=headers, json={}) as response:
                    assert response.status == 404
        finally:
            await preview.close()


def test_profile_pairing_survives_listener_restart(tmp_path):
    asyncio.run(_exercise_saved_pairing(tmp_path))


async def _exercise_saved_pairing(tmp_path):
    import json
    from gateway.mobile_preview import PROFILE_PAIRING_KEY
    from hermes_state import SessionDB

    interface = ipaddress.IPv4Interface("127.0.0.1/8")
    path = tmp_path / "saved-pairing.db"
    async with ClientSession() as client:
        with SessionDB(path) as db:
            authority = SimpleNamespace(db=db, profile_id="default")
            preview = MobilePreview(authority, interface, sync_profile=True, pairing_store=db)
            await preview.start()
            try:
                _, *fields = preview.code.split(".")
                origin, challenge, cert = [base64.urlsafe_b64decode(field + "=" * (-len(field) % 4))
                                            for field in fields]
                origin = origin.decode()
                tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
                async with client.post(origin + "/meu/pair", ssl=tls,
                                       json={"challenge": challenge.decode()}) as response:
                    assert response.status == 200
                    key = (await response.json())["key"]
                assert preview.state()["seconds"] is None
                assert key not in db.get_meta(PROFILE_PAIRING_KEY)
            finally:
                await preview.close()

        with SessionDB(path) as db:
            saved = json.loads(db.get_meta(PROFILE_PAIRING_KEY))
            authority = SimpleNamespace(db=db, profile_id="default")
            restored = MobilePreview(authority, interface, sync_profile=True, pairing_store=db)
            await restored.start(saved=saved)
            try:
                async with client.get(origin + "/meu/sync/sessions", ssl=tls,
                                      headers={"Authorization": f"Bearer {key}"}) as response:
                    assert response.status == 200
                async with client.post(origin + "/meu/pair", ssl=tls,
                                       json={"challenge": challenge.decode()}) as response:
                    assert response.status == 401
                async with client.get(origin + "/meu/sync/sessions", ssl=tls,
                                      headers={"Authorization": "Bearer incorrect"}) as response:
                    assert response.status == 401
            finally:
                await restored.close()
