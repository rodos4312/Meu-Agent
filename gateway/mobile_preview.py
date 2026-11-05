"""Temporary, profile-bound LAN listener for the native Meu Android preview."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import re
import secrets
import socket
import ssl
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiohttp import web

PAIR_SECONDS = 300
SESSION_SECONDS = 3600
PRIVATE_NETWORKS = tuple(map(ipaddress.IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
KEY_PATTERN = re.compile(r"[0-9a-f-]{36}", re.ASCII)
MAX_RUNS = 32
logger = logging.getLogger(__name__)


def local_network():
    """Use the private IPv4 interface selected by the OS for its default route."""
    import psutil

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))  # Selects a route without sending a datagram.
        address = ipaddress.IPv4Address(probe.getsockname()[0])
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError("Connect this computer to a private local network first.")
    for addresses in psutil.net_if_addrs().values():
        for item in addresses:
            if item.family == socket.AF_INET and item.address == str(address) and item.netmask:
                return ipaddress.IPv4Interface(f"{address}/{item.netmask}")
    raise ValueError("Meu could not find the local network for this computer.")


def _tls(address: str) -> tuple[ssl.SSLContext, bytes]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from agent.ssl_verify import _stdlib_ssl_context_class

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Meu LAN Preview")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address(address))]), False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
            .sign(key, hashes.SHA256()))
    # Use Python's server defaults (TLS 1.2+) without the gateway's outgoing OS trust adapter.
    context = _stdlib_ssl_context_class()(ssl.PROTOCOL_TLS_SERVER)
    with tempfile.TemporaryDirectory(prefix="meu-mobile-tls-") as folder:
        pem = Path(folder) / "tls.pem"
        pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context.load_cert_chain(str(pem))
    return context, cert.public_bytes(serialization.Encoding.DER)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class _MobileTransport:
    def write(self, _event):
        # The HTTP preview polls canonical receipts. Nothing streams over this transport.
        return True


class MobilePreview:
    def __init__(self, authority, interface):
        self.authority = authority
        self.interface = interface
        self.loop = asyncio.get_running_loop()
        self.deadline = 0
        self.expiry = None
        self.runner = None
        self.code = None
        self.challenge = secrets.token_urlsafe(32)
        self.token = None
        self.connection = None
        self.session = None
        self.session_request = uuid.uuid4().hex
        self.runs = {}
        self.lock = asyncio.Lock()

    async def start(self):
        tls, certificate = await asyncio.to_thread(_tls, str(self.interface.ip))
        app = web.Application(client_max_size=48 * 1024, middlewares=[self._guard])
        app.add_routes([
            web.post("/meu/pair", self._pair),
            web.get("/v1/capabilities", self._capabilities, allow_head=False),
            web.post("/v1/runs", self._submit),
            web.get("/v1/runs/{run_id}", self._status, allow_head=False),
        ])
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        await runner.setup()
        try:
            await web.TCPSite(runner, str(self.interface.ip), 0, ssl_context=tls).start()
        except BaseException:
            await runner.cleanup()
            raise
        self.runner = runner
        port = runner.addresses[0][1]
        origin = f"https://{self.interface.ip}:{port}"
        self.code = ".".join(("meu2", _encode(origin.encode()), _encode(self.challenge.encode()), _encode(certificate)))
        self._expire_in(PAIR_SECONDS)

    def _expire_in(self, seconds):
        if self.expiry:
            self.expiry.cancel()
        self.deadline = self.loop.time() + seconds
        self.expiry = self.loop.call_later(seconds, lambda: self.loop.create_task(self.close()))

    def state(self):
        if self.loop.time() >= self.deadline or not self.runner:
            return {"state": "off"}
        return {"state": "paired" if self.token else "waiting", "code": self.code,
                "seconds": max(0, round(self.deadline - self.loop.time()))}

    async def close(self):
        if self.expiry:
            self.expiry.cancel()
        self.deadline = 0
        self.code = self.challenge = self.token = None
        runner, self.runner = self.runner, None
        connection, self.connection = self.connection, None
        try:
            if runner:
                await runner.cleanup()
        finally:
            if connection:
                await connection.close()
            self.runs.clear()

    @web.middleware
    async def _guard(self, request, handler):
        if ("Origin" in request.headers or not request.remote
                or ipaddress.IPv4Address(request.remote) not in self.interface.network):
            raise web.HTTPForbidden()
        if self.loop.time() >= self.deadline or getattr(self.authority, "retiring", False):
            raise web.HTTPGone()
        if request.path != "/meu/pair":
            expected = f"Bearer {self.token}" if self.token else ""
            supplied = request.headers.get("Authorization", "")
            if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
                raise web.HTTPUnauthorized()
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @staticmethod
    async def _json(request):
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest()
        return body

    async def _pair(self, request):
        from gateway.session_controls import AuthorityConnection

        body = await self._json(request)
        challenge = body.get("challenge")
        if not (self.challenge and isinstance(challenge, str)
                and secrets.compare_digest(self.challenge.encode(), challenge.encode())):
            raise web.HTTPUnauthorized()
        identity = {"user_id": f"mobile-preview-{uuid.uuid4().hex}", "provider": "meu-mobile",
                    "profile_id": self.authority.profile_id, "instance_id": self.authority.instance_id,
                    "capabilities": ["session:create", "session:read", "session:submit"]}
        self.connection = AuthorityConnection(self.authority, _MobileTransport(), identity)
        self.challenge = self.code = None
        self.token = secrets.token_urlsafe(32)
        self._expire_in(SESSION_SECONDS)
        return web.json_response({"key": self.token})

    async def _capabilities(self, _request):
        return web.json_response({"auth": {"required": True}, "features": {
            "run_submission": True, "run_status": True,
            "runs_idempotency": {"pairing_session": True, "retention_seconds": SESSION_SECONDS}}})

    async def _call(self, method, params):
        if self.connection is None:
            raise web.HTTPGone()
        result = await self.connection.dispatch({"id": "mobile", "method": method, "params": params})
        if not result or not isinstance(result.get("result"), dict):
            error = (result or {}).get("error", {})
            logger.warning("Mobile preview %s refused: %s", method, error.get("data", {}).get("reason", "unknown"))
            raise web.HTTPConflict()
        return result["result"]

    async def _submit(self, request):
        body = await self._json(request)
        text = body.get("input")
        key = request.headers.get("Idempotency-Key", "")
        if (set(body) - {"input", "session_id"} or not isinstance(text, str)
                or not text.strip() or len(text) > 8000 or not KEY_PATTERN.fullmatch(key)):
            raise web.HTTPBadRequest()
        async with self.lock:
            if key in self.runs:
                previous, _ = self.runs[key]
                if previous != text:
                    raise web.HTTPConflict()
            else:
                if len(self.runs) >= MAX_RUNS:
                    raise web.HTTPTooManyRequests()
                if self.session is None:
                    session = await self._call("session.create", {
                        "source": "cli", "request_id": self.session_request, "toolsets": [],
                        "ignore_rules": True, "run_budget": 120,
                    })
                    self.session = session["session_id"]
                receipt = await self._call("prompt.submit", {
                    "session_id": self.session, "text": text, "input_id": key,
                })
                self.runs[key] = (text, receipt["admission_id"])
        return web.json_response({"run_id": f"run_{key}"}, status=202)

    async def _status(self, request):
        run_id = request.match_info["run_id"]
        run = self.runs.get(run_id.removeprefix("run_")) if run_id.startswith("run_") else None
        if run is None:
            raise web.HTTPNotFound()
        receipt = await self._call("prompt.receipt", {
            "session_id": self.session, "admission_id": run[1], "include_result": True,
        })
        status = receipt["status"]
        result = receipt.get("result")
        answer = ""
        if status == "terminal":
            outcome = receipt.get("outcome")
            status = outcome if outcome in {"completed", "cancelled", "interrupted"} else "failed"
            if isinstance(result, dict):
                answer = result.get("final_response") or ""
        return web.json_response({"run_id": run_id, "status": status, "output": answer})
