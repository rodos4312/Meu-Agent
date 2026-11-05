"""Meu's Windows-side encrypted link to an opaque mobile relay."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import suppress
from hashlib import sha256
import json
import logging
import re
import secrets
import time

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from yarl import URL

from gateway.mobile_relay import MAX_PACKET

logger = logging.getLogger(__name__)
_READ = re.compile(r"/(?:meu/sessions(?:/local-[0-9a-f]{64})?|v1/capabilities|v1/runs/run_[0-9a-f-]{36})")
_WRITE = {"/meu/pair", "/meu/sessions", "/v1/runs"}
_ID = re.compile(r"[0-9a-f-]{36}")
_KEY = re.compile(r"[A-Za-z0-9_-]{32,128}")
_REVISION = re.compile(r"[0-9a-f]{64}")


class MobileRelayLink:
    def __init__(self, endpoint, local_origin, local_tls):
        base = URL(endpoint)
        if (base.scheme != "https" or not base.host or base.user is not None
                or base.query_string or base.fragment or base.path != "/"):
            raise ValueError("The Meu relay must be an HTTPS origin.")
        self.host_key = secrets.token_urlsafe(32)
        room = sha256(self.host_key.encode()).hexdigest()
        self.host_url = base / "v1" / room / "host"
        self.exchange_url = base / "v1" / room / "exchange"
        self.secret = secrets.token_bytes(32)
        self.inbound = AESGCM(sha256(b"meu request v1" + self.secret).digest())
        self.outbound = AESGCM(sha256(b"meu response v1" + self.secret).digest())
        self.local_origin = local_origin
        self.local_tls = local_tls
        self.seen = OrderedDict()
        self.client = None
        self.task = None

    async def start(self):
        self.client = ClientSession(timeout=ClientTimeout(total=8), trust_env=False)
        try:
            socket = await self._connect()
        except BaseException:
            await self.client.close()
            raise
        self.task = asyncio.create_task(self._run(socket))

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.client is not None:
            await self.client.close()

    async def _connect(self):
        return await self.client.ws_connect(
            self.host_url, headers={"Authorization": f"Bearer {self.host_key}"},
            heartbeat=25, max_msg_size=MAX_PACKET + 16,
        )

    async def _run(self, socket):
        while True:
            try:
                async with socket:
                    async for message in socket:
                        if message.type == WSMsgType.BINARY and len(message.data) >= 44:
                            reply = await self._exchange(message.data[16:])
                            await socket.send_bytes(message.data[:16] + reply)
            except (ClientError, OSError, TimeoutError):
                logger.debug("Meu mobile relay disconnected.")
            while True:
                await asyncio.sleep(3)
                try:
                    socket = await self._connect()
                    break
                except (ClientError, OSError, TimeoutError):
                    continue

    async def _exchange(self, packet):
        nonce = packet[:12]
        try:
            message = json.loads(self.inbound.decrypt(nonce, packet[12:], None))
        except (InvalidTag, ValueError):
            # A caller without the device secret gets no encrypted plaintext or timing-dependent detail.
            return b"\0"
        now = time.monotonic()
        while self.seen and next(iter(self.seen.values())) < now - 180:
            self.seen.popitem(last=False)
        if (not isinstance(message, dict) or type(message.get("at")) is not int
                or abs(time.time() - message["at"]) > 60 or nonce in self.seen or len(self.seen) >= 512):
            return self._reply(nonce, 409, {})
        self.seen[nonce] = now
        try:
            status, body = await self._dispatch(message)
        except (ClientError, OSError, TimeoutError, ValueError):
            status, body = 502, {}
        return self._reply(nonce, status, body)

    def _reply(self, request_nonce, status, body):
        nonce = secrets.token_bytes(12)
        payload = json.dumps({"status": status, "body": body}, ensure_ascii=False).encode()
        if len(payload) + 28 > MAX_PACKET:
            payload = b'{"status":502,"body":{}}'
        return nonce + self.outbound.encrypt(nonce, payload, request_nonce)

    async def _dispatch(self, message):
        path, method = message.get("path"), message.get("method")
        if not isinstance(path, str):
            return 400, {}
        path, mark, query = path.partition("?")
        if method == "GET":
            if not _READ.fullmatch(path) or (mark and (
                not path.startswith("/meu/sessions/local-") or not query.startswith("since=")
                or not _REVISION.fullmatch(query[6:])
            )):
                return 404, {}
        elif method != "POST" or mark or path not in _WRITE or not isinstance(message.get("body"), dict):
            return 404, {}
        headers = {}
        key, request_id = message.get("key"), message.get("id")
        if isinstance(key, str) and _KEY.fullmatch(key):
            headers["Authorization"] = f"Bearer {key}"
        if isinstance(request_id, str) and _ID.fullmatch(request_id):
            headers["Idempotency-Key"] = request_id
        async with self.client.request(
            method, self.local_origin + path + mark + query, headers=headers,
            json=message.get("body") if method == "POST" else None,
            ssl=self.local_tls, allow_redirects=False,
        ) as response:
            body = await response.json() if response.status < 300 else {}
            return response.status, body
