"""Exercise the real relay, both TLS legs, and the phone's encrypted wire format."""

import asyncio
import base64
from hashlib import sha256
import ipaddress
import json
import secrets
import ssl
import time
from types import SimpleNamespace

from aiohttp import ClientSession, TCPConnector, web
from aiohttp.test_utils import TestServer
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agent.ssl_verify import _stdlib_ssl_context_class
from gateway import mobile_relay_link
from gateway.mobile_preview import MobilePreview, _tls
from gateway.mobile_relay import make_relay_app


def test_relay_reconnects_without_repairing_and_refuses_replays(monkeypatch):
    async def exercise():
        listener_tls, cert = _tls("127.0.0.1", 3600)
        trust = _stdlib_ssl_context_class()(ssl.PROTOCOL_TLS_CLIENT)
        trust.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert))
        seen = []

        async def sessions(request):
            if request.headers.get("Authorization") != "Bearer " + "a" * 43:
                raise web.HTTPUnauthorized()
            seen.append(request.path)
            return web.json_response({"sessions": [{"title": "Private test title"}]})

        local_app = web.Application()
        local_app.add_routes([web.get("/meu/sessions", sessions), web.get("/internal", sessions)])
        local = TestServer(local_app)
        relay = TestServer(make_relay_app())
        await local.start_server(ssl=listener_tls)
        await relay.start_server(ssl=listener_tls)
        async with local, relay:
            monkeypatch.setattr(mobile_relay_link, "ClientSession",
                                lambda **kw: ClientSession(connector=TCPConnector(ssl=trust), **kw))
            link = mobile_relay_link.MobileRelayLink(str(relay.make_url("/")), str(local.make_url("/")).rstrip("/"), trust)
            await link.start()
            try:
                encrypt = AESGCM(sha256(b"meu request v1" + link.secret).digest())
                decrypt = AESGCM(sha256(b"meu response v1" + link.secret).digest())

                def packet(path):
                    nonce = secrets.token_bytes(12)
                    raw = json.dumps({"at": int(time.time()), "method": "GET", "path": path,
                                      "key": "a" * 43}).encode()
                    return nonce + encrypt.encrypt(nonce, raw, None)

                async def exchange(blob):
                    # A new Android HTTP client can use the saved pairing identity after reopening.
                    async with ClientSession(connector=TCPConnector(ssl=trust)) as phone:
                        async with phone.post(link.exchange_url, data=blob) as response:
                            assert response.status == 200
                            return await response.read()

                def decode(blob, reply):
                    assert b"Private test title" not in reply
                    return json.loads(decrypt.decrypt(reply[:12], reply[12:], blob[:12]))

                sent = packet("/meu/sessions")
                assert decode(sent, await exchange(sent)) == {
                    "status": 200, "body": {"sessions": [{"title": "Private test title"}]},
                }
                assert decode(sent, await exchange(sent))["status"] == 409
                assert await exchange(sent[:-1] + bytes([sent[-1] ^ 1])) == b"\0"
                blocked = packet("/internal")
                assert decode(blocked, await exchange(blocked))["status"] == 404
                again = packet("/meu/sessions")
                assert decode(again, await exchange(again))["status"] == 200
                assert seen == ["/meu/sessions", "/meu/sessions"]
            finally:
                await link.close()
            async with ClientSession(connector=TCPConnector(ssl=trust)) as phone:
                async with phone.post(link.exchange_url, data=sent) as response:
                    assert response.status == 503

    asyncio.run(exercise())


def test_mobile_preview_pairs_through_relay_and_revokes_device(monkeypatch):
    async def exercise():
        listener_tls, cert = _tls("127.0.0.1", 3600)
        trust = _stdlib_ssl_context_class()(ssl.PROTOCOL_TLS_CLIENT)
        trust.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert))
        relay = TestServer(make_relay_app())
        await relay.start_server(ssl=listener_tls)
        async with relay:
            monkeypatch.setattr(mobile_relay_link, "ClientSession",
                                lambda **kw: ClientSession(connector=TCPConnector(ssl=trust), **kw))
            authority = SimpleNamespace(profile_id="fixture", instance_id="fixture", events={})
            preview = MobilePreview(authority, ipaddress.IPv4Interface("127.0.0.1/32"), remote=True,
                                    relay_url=str(relay.make_url("/")))
            await preview.start()
            try:
                version, *parts = preview.code.split(".")
                assert version == "meu3"
                exchange_url, challenge, secret = (base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
                                                    for part in parts)
                encrypt = AESGCM(sha256(b"meu request v1" + secret).digest())
                decrypt = AESGCM(sha256(b"meu response v1" + secret).digest())

                async def send(path, *, body=None, key=None):
                    nonce = secrets.token_bytes(12)
                    raw = json.dumps({"at": int(time.time()), "method": "POST" if body is not None else "GET",
                                      "path": path, "body": body, "key": key}).encode()
                    async with ClientSession(connector=TCPConnector(ssl=trust)) as phone:
                        async with phone.post(exchange_url.decode(), data=nonce + encrypt.encrypt(nonce, raw, None)) as reply:
                            packet = await reply.read()
                            if reply.status != 200:
                                return reply.status, {}
                    result = json.loads(decrypt.decrypt(packet[:12], packet[12:], nonce))
                    return result["status"], result["body"]

                assert (await send("/v1/capabilities"))[0] == 401
                payload = {"challenge": challenge.decode()}
                status, enrolled = await send("/meu/pair", body=payload)
                assert status == 200
                assert preview.state()["state"] == "paired"
                assert (await send("/meu/pair", body=payload))[0] == 401
                status, capabilities = await send("/v1/capabilities", key=enrolled["key"])
                assert status == 200 and capabilities["features"]["mobile_sessions"]
            finally:
                await preview.close()
            assert (await send("/v1/capabilities", key=enrolled["key"]))[0] == 503

    asyncio.run(exercise())
