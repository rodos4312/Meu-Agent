"""A missing network adapter must not discard a usable sync listener."""

import asyncio
import base64
import ipaddress
import ssl
from types import SimpleNamespace

import pytest
from aiohttp import ClientSession, web

from gateway.mobile_preview import MobilePreview


@pytest.mark.parametrize("failed_address", ["127.0.0.1", "127.0.0.2"])
def test_sync_pairing_advertises_only_interfaces_that_bound(monkeypatch, failed_address):
    original_site = web.TCPSite

    class UnavailableSite:
        async def start(self):
            raise OSError("Adapter is temporarily unavailable")

    def site(runner, address, port, **kwargs):
        if address == failed_address:
            return UnavailableSite()
        return original_site(runner, address, port, **kwargs)

    monkeypatch.setattr(web, "TCPSite", site)
    asyncio.run(_exercise_partial_start(failed_address))


async def _exercise_partial_start(failed_address):
    preview = MobilePreview(
        SimpleNamespace(db=SimpleNamespace()),
        ipaddress.IPv4Interface("127.0.0.1/8"), sync_profile=True,
        sync_tailscale=ipaddress.IPv4Interface("127.0.0.2/8"),
    )
    try:
        await preview.start()
        _, *fields = preview.code.split(".")
        origins, challenge, cert = [base64.urlsafe_b64decode(field + "=" * (-len(field) % 4))
                                    for field in fields]
        available = "127.0.0.2" if failed_address == "127.0.0.1" else "127.0.0.1"
        advertised = origins.decode().splitlines()
        assert len(advertised) == 1
        assert advertised[0].startswith(f"https://{available}:")
        assert [str(interface.ip) for interface in preview.interfaces] == [available]
        assert len(preview.ports) == 1
        assert preview.state()["listener_count"] == 1
        assert preview.state()["offline"] is False
        assert preview.state()["last_contact"] is None
        tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
        async with ClientSession() as client:
            async with client.get(advertised[0] + "/meu/sync/sessions", ssl=tls) as response:
                assert response.status == 401
            assert preview.state()["last_contact"] is None
            async with client.post(advertised[0] + "/meu/pair", ssl=tls,
                                   json={"challenge": challenge.decode()}) as response:
                assert response.status == 200
            assert preview.state()["last_contact"] is not None
    finally:
        await preview.close()


def test_sync_pairing_fails_cleanly_when_no_interface_bound(monkeypatch):
    class UnavailableSite:
        async def start(self):
            raise OSError("Adapter is temporarily unavailable")

    monkeypatch.setattr(web, "TCPSite", lambda *args, **kwargs: UnavailableSite())

    async def exercise():
        preview = MobilePreview(SimpleNamespace(), ipaddress.IPv4Interface("127.0.0.1/8"),
                                sync_profile=True)
        with pytest.raises(OSError):
            await preview.start()
        assert preview.runner is None
        assert preview.code is None
        assert preview.state() == {"state": "off"}

    asyncio.run(exercise())
