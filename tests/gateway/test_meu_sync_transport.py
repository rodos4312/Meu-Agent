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
    session_id = "local-" + "a" * 64
    history = {"id": session_id, "messages": []}
    applied = []

    def export(requested_id):
        assert requested_id == session_id
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
