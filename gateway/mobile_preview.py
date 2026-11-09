"""Temporary, profile-bound private listener for the native Meu Android preview."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import logging
import re
import secrets
import socket
import ssl
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from aiohttp import web

from gateway.session_policy import MOBILE_SESSION_PREFIX

PROFILE_PAIRING_KEY = "meu.profile-sync.pairing.v1"
PROFILE_CERT_SECONDS = 365 * 24 * 3600
PAIR_SECONDS = 300
SESSION_SECONDS = 3600
REMOTE_SESSION_SECONDS = 12 * 3600
PRIVATE_NETWORKS = tuple(map(ipaddress.IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
TAILSCALE_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")
KEY_PATTERN = re.compile(r"[0-9a-f-]{36}", re.ASCII)
MAX_RUNS = 32
SESSION_PATTERN = re.compile(r"local-[0-9a-f]{64}", re.ASCII)
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


def tailscale_network():
    """Find Tailscale's local IPv4 interface, independently of the default route."""
    import psutil

    for name, addresses in psutil.net_if_addrs().items():
        if name.casefold() not in {"tailscale", "tailscale0"}:
            continue
        for item in addresses:
            if item.family == socket.AF_INET and ipaddress.IPv4Address(item.address) in TAILSCALE_NETWORK:
                return ipaddress.IPv4Interface(f"{item.address}/{TAILSCALE_NETWORK.prefixlen}")
    raise ValueError("Connect Tailscale on this computer before pairing.")


def _tls(address: str, session_seconds: int, *, extra_addresses=(), saved_pem=None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    if saved_pem is not None:
        cert = x509.load_pem_x509_certificate(saved_pem)
        return _tls_context(saved_pem), cert.public_bytes(serialization.Encoding.DER), saved_pem

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Meu Android Preview")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(seconds=session_seconds + PAIR_SECONDS + 60))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address(ip)) for ip in (address, *extra_addresses)]), False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return _tls_context(pem), cert.public_bytes(serialization.Encoding.DER), pem


def _tls_context(contents):
    from agent.ssl_verify import _stdlib_ssl_context_class

    context = _stdlib_ssl_context_class()(ssl.PROTOCOL_TLS_SERVER)
    with tempfile.TemporaryDirectory(prefix="meu-mobile-tls-") as folder:
        pem = Path(folder) / "tls.pem"
        pem.write_bytes(contents)
        context.load_cert_chain(str(pem))
    return context


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class _MobileTransport:
    def write(self, _event):
        # The HTTP preview polls canonical receipts. Nothing streams over this transport.
        return True


class MobilePreview:
    def __init__(self, authority, interface, *, remote=False, relay_url=None,
                 sync_session=None, sync_tailscale=None, sync_profile=False, pairing_store=None,
                 personal_devices=None, device_id=None):
        self.authority = authority
        self.interface = interface
        self.remote = remote
        self.relay_url = relay_url
        self.sync_session = sync_session
        self.sync_profile = sync_profile
        self.pairing_store = pairing_store
        self.personal_devices = personal_devices
        self.device_id = device_id
        space = personal_devices.scope(authority.profile_id, device_id)[1] if personal_devices else None
        self.personal_space = space['id'] if space and not space.get('owner') else None
        self.token_digest = None
        self.tls_pem = None
        self.tls_context = None
        self.ports = ()
        self.sync_enabled = bool(sync_session or sync_profile)
        self.interfaces = (interface, sync_tailscale) if sync_tailscale else (interface,)
        self.relay = None
        self.session_seconds = REMOTE_SESSION_SECONDS if remote or sync_tailscale else SESSION_SECONDS
        self.loop = asyncio.get_running_loop()
        self.deadline = 0
        self.expiry = None
        self.runner = None
        self.code = None
        self.challenge = secrets.token_urlsafe(32)
        self.token = None
        self.connection = None
        self.legacy_session = None
        self.legacy_request = str(uuid.uuid4())
        self.runs = {}
        self.lock = asyncio.Lock()
        self.last_contact = None
        self.live_sockets = set()

    async def start(self, *, saved=None):
        addresses = tuple(str(interface.ip) for interface in self.interfaces)
        tls, certificate, self.tls_pem = await asyncio.to_thread(
            _tls, addresses[0], PROFILE_CERT_SECONDS if self.sync_profile and self.pairing_store else self.session_seconds,
            extra_addresses=addresses[1:], saved_pem=saved["pem"].encode("ascii") if saved else None,
        )
        app = web.Application(
            client_max_size=2 * 1024 * 1024 if self.sync_enabled else 48 * 1024,
            middlewares=[self._guard],
        )
        app.router.add_post("/meu/pair", self._pair)
        from gateway.mobile_transfers import mount as mount_transfers
        mount_transfers(app, self)
        if self.sync_profile:
            from gateway.mobile_live import serve as serve_live
            from gateway.mobile_live import readiness as live_readiness
            from gateway.mobile_live import observation
            app.router.add_get('/meu/live', lambda request: serve_live(self, request), allow_head=False)
            app.router.add_get('/meu/live/sessions/{session_id}', lambda request: live_readiness(self, request), allow_head=False)
            app.router.add_get('/meu/observe/{session_id}', lambda request: observation(self, request), allow_head=False)
            app.router.add_put('/meu/observe/{session_id}', lambda request: observation(self, request))
            app.router.add_get("/meu/sync/sessions", self._sync_catalog, allow_head=False)
            app.router.add_get("/meu/sync/sessions/{session_id}", self._sync_export, allow_head=False)
            app.router.add_put("/meu/sync/sessions/{session_id}", self._sync_apply)
            app.router.add_post("/meu/sync/sessions/{session_id}/resolve", self._sync_resolve)
            app.router.add_get("/meu/sync/backups", self._sync_backups, allow_head=False)
            app.router.add_get("/meu/sync/sessions/{session_id}/backups/{receipt}", self._sync_backups, allow_head=False)
        elif self.sync_session:
            app.router.add_get("/meu/sync", self._sync_export, allow_head=False)
            app.router.add_put("/meu/sync", self._sync_apply)
        else:
            app.add_routes([
                web.get("/meu/sessions", self._list_sessions, allow_head=False),
                web.post("/meu/sessions", self._new_session),
                web.get("/meu/sessions/{session_id}", self._open_session, allow_head=False),
                web.get("/v1/capabilities", self._capabilities, allow_head=False),
                web.post("/v1/runs", self._submit),
                web.get("/v1/runs/{run_id}", self._status, allow_head=False),
            ])
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        await runner.setup()
        try:
            for index, address in enumerate(addresses):
                port = saved["ports"][index] if saved else 0
                try:
                    await web.TCPSite(runner, address, port, ssl_context=tls).start()
                except OSError as exc:
                    if not saved and not self.sync_enabled:
                        raise
                    logger.warning("Meu sync interface %d could not bind (errno=%s)", index, exc.errno)
            if not runner.addresses:
                raise OSError("No sync address is available")
        except BaseException:
            await runner.cleanup()
            raise
        self.runner = runner
        self.tls_context = tls
        if saved:
            self.ports = tuple(saved["ports"])
            self.challenge = self.code = None
            self.token_digest = saved["digest"]
            self._keep_paired()
            return
        # Advertise and persist only endpoints which actually started. A stale VPN
        # adapter must not close a usable LAN listener (or the other way around).
        bound = {ip for ip, _ in runner.addresses}
        self.interfaces = tuple(interface for interface in self.interfaces if str(interface.ip) in bound)
        self.interface = self.interfaces[0]
        addresses = tuple(str(interface.ip) for interface in self.interfaces)
        self.ports = tuple(next(port for ip, port in runner.addresses if ip == address) for address in addresses)
        origins = tuple(
            f"https://{address}:{next(port for ip, port in runner.addresses if ip == address)}"
            for address in addresses
        )
        origin = origins[0]
        if self.sync_enabled:
            # One challenge and credential cover the LAN-first list of pinned origins.
            self.code = ".".join(("meusync2" if self.sync_profile else "meusync1", _encode("\n".join(origins).encode()),
                                  _encode(self.challenge.encode()), _encode(certificate)))
        elif self.relay_url:
            from agent.ssl_verify import _stdlib_ssl_context_class
            from gateway.mobile_relay_link import MobileRelayLink

            trust = _stdlib_ssl_context_class()(ssl.PROTOCOL_TLS_CLIENT)
            trust.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
            try:
                self.relay = MobileRelayLink(self.relay_url, origin, trust)
                await self.relay.start()
            except BaseException:
                await self.close()
                raise
            self.code = ".".join(("meu3", _encode(str(self.relay.exchange_url).encode()),
                                  _encode(self.challenge.encode()), _encode(self.relay.secret)))
        else:
            self.code = ".".join(("meu2", _encode(origin.encode()), _encode(self.challenge.encode()), _encode(certificate)))
        self._expire_in(PAIR_SECONDS)

    async def restore_missing_sites(self):
        if not self.runner or not self.token_digest or not self.tls_context:
            return
        bound = {address for address, _ in self.runner.addresses}
        for interface, port in zip(self.interfaces, self.ports, strict=True):
            address = str(interface.ip)
            if address not in bound:
                try:
                    await web.TCPSite(self.runner, address, port, ssl_context=self.tls_context).start()
                except OSError:
                    pass

    def _expire_in(self, seconds):
        if self.expiry:
            self.expiry.cancel()
        self.deadline = self.loop.time() + seconds
        self.expiry = self.loop.call_later(seconds, lambda: self.loop.create_task(self.close()))

    def _keep_paired(self):
        if self.expiry:
            self.expiry.cancel()
            self.expiry = None
        self.deadline = float("inf")

    def state(self):
        if self.loop.time() >= self.deadline or not self.runner:
            return {"state": "off"}
        return {"state": "paired" if self.token or self.token_digest else "waiting", "code": self.code,
                "seconds": None if self.token_digest else max(0, round(self.deadline - self.loop.time())),
                **({"sync": True, "listener_count": len(self.runner.addresses),
                    "offline": not bool(self.runner.addresses),
                    "last_contact": self.last_contact} if self.sync_enabled else {}),
                **({"sync_profile": True} if self.sync_profile else {})}

    async def close(self):
        if self.expiry:
            self.expiry.cancel()
        self.deadline = 0
        self.code = self.challenge = self.token = self.token_digest = None
        runner, self.runner = self.runner, None
        connection, self.connection = self.connection, None
        relay, self.relay = self.relay, None
        try:
            if relay:
                await relay.close()
        finally:
            await self._close_listener(runner, connection)

    async def _close_listener(self, runner, connection):
        try:
            await asyncio.gather(*(socket.close() for socket in tuple(self.live_sockets)))
            if runner:
                await runner.cleanup()
        finally:
            if connection:
                await connection.close()
            self.runs.clear()

    @web.middleware
    async def _guard(self, request, handler):
        if self.personal_devices:
            from fastapi import HTTPException
            try:
                await asyncio.to_thread(self.personal_devices.scope, self.authority.profile_id, self.device_id)
            except HTTPException:
                raise web.HTTPGone() from None
        local = request.transport.get_extra_info("sockname") if request.transport else None
        interface = next((item for item in self.interfaces if local and str(item.ip) == local[0]), None)
        if ("Origin" in request.headers or not request.remote or interface is None
                or ipaddress.ip_address(request.remote) not in interface.network):
            raise web.HTTPForbidden()
        if self.loop.time() >= self.deadline or getattr(self.authority, "retiring", False):
            raise web.HTTPGone()
        if request.path != "/meu/pair":
            expected = f"Bearer {self.token}" if self.token else ""
            supplied = request.headers.get("Authorization", "")
            if self.token_digest:
                valid = supplied.startswith("Bearer ") and secrets.compare_digest(
                    self.token_digest, sha256(supplied[7:].encode()).hexdigest())
            else:
                valid = bool(expected) and secrets.compare_digest(expected.encode(), supplied.encode())
            if not valid:
                raise web.HTTPUnauthorized()
            self.last_contact = datetime.now(UTC).isoformat()
            if self.personal_devices:
                await asyncio.to_thread(self.personal_devices.contact, self.authority.profile_id,
                                        self.device_id, self.last_contact)
        response = await handler(request)
        if request.path == "/meu/pair" and response.status == 200:
            self.last_contact = datetime.now(UTC).isoformat()
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
        body = await self._json(request)
        challenge = body.get("challenge")
        if not (self.challenge and isinstance(challenge, str)
                and secrets.compare_digest(self.challenge.encode(), challenge.encode())):
            raise web.HTTPUnauthorized()
        if self.sync_profile and self.pairing_store:
            async with self.lock:
                if self.challenge != challenge or self.loop.time() >= self.deadline:
                    raise web.HTTPUnauthorized()
                key = secrets.token_urlsafe(32)
                digest = sha256(key.encode()).hexdigest()
                record = {"profile": self.authority.profile_id, "digest": digest,
                          "pem": self.tls_pem.decode("ascii"), "ports": self.ports,
                          "interfaces": [str(interface) for interface in self.interfaces]}
                remaining = self.deadline - self.loop.time()
                self._keep_paired()
                try:
                    if self.personal_devices:
                        await asyncio.to_thread(self.personal_devices.paired, self.authority.profile_id,
                                                self.device_id, record)
                    else:
                        await asyncio.to_thread(self.pairing_store.set_meta, PROFILE_PAIRING_KEY, json.dumps(record))
                except Exception:
                    self._expire_in(max(0, remaining))
                    raise
                self.challenge = self.code = None
                self.token_digest = digest
                metadata = {}
                if self.personal_devices:
                    device, space = self.personal_devices.scope(self.authority.profile_id, self.device_id)
                    metadata = {'space_id': space['id'], 'space_name': space['name'], 'device_id': device['id']}
                return web.json_response({"key": key, **metadata})
        if self.sync_enabled:
            self.challenge = self.code = None
            self.token = secrets.token_urlsafe(32)
            self._expire_in(self.session_seconds)
            return web.json_response({"key": self.token})
        from gateway.owner_identity import host_owner_subject
        from gateway.session_controls import AuthorityConnection

        # The pairing belongs to this Desktop user. Only the fixed routes below may use it,
        # and they only address sessions created by this listener.
        identity = {"user_id": host_owner_subject(), "provider": "local",
                    "profile_id": self.authority.profile_id, "instance_id": self.authority.instance_id,
                    "capabilities": ["session:create", "session:read", "session:submit"]}
        self.connection = AuthorityConnection(self.authority, _MobileTransport(), identity)
        self.challenge = self.code = None
        self.token = secrets.token_urlsafe(32)
        self._expire_in(self.session_seconds)
        return web.json_response({"key": self.token})

    async def _sync_catalog(self, request):
        try:
            catalog = await asyncio.to_thread(
                self.authority.db.list_meu_sync_sessions, after=request.query.get("after", ""),
                fingerprints=request.query.get("fingerprints") == "1",
                **({'personal_space': self.personal_space} if self.personal_space else {}),
            )
        except ValueError:
            raise web.HTTPBadRequest() from None
        return web.json_response({**catalog,
            **({"observations": 1} if request.query.get("live") == "1" else {}),
            **({"live_chat": 1} if request.query.get("live") == "1" else {}),
            **({"timestamps": True} if request.query.get("timestamps") == "1" else {}),
            **({"sync_recovery": 1} if request.query.get("recovery") == "1" else {})})

    async def _sync_resolve(self, request):
        from hermes_state_errors import (
            SessionActiveWriteGuardError, SessionCompressionInProgressError, SessionTurnLeaseLostError,
        )

        resolution = await self._json(request)
        sid = request.match_info["session_id"]
        if not isinstance(resolution.get("pc"), dict) or resolution["pc"].get("id") != sid:
            raise web.HTTPForbidden()
        try:
            async with self.lock:
                result = await asyncio.to_thread(self.authority.db.resolve_meu_sync_history,
                    resolution, personal_space=self.personal_space)
        except LookupError:
            raise web.HTTPNotFound() from None
        except ValueError:
            raise web.HTTPBadRequest() from None
        except (SessionActiveWriteGuardError, SessionCompressionInProgressError, SessionTurnLeaseLostError):
            return web.json_response({"status": "busy"}, status=409)
        return web.json_response(result)

    async def _sync_backups(self, request):
        try:
            result = await asyncio.to_thread(self.authority.db.list_meu_sync_backups,
                session_id=request.match_info.get("session_id"), receipt=request.match_info.get("receipt"),
                personal_space=self.personal_space)
            if request.query.get("side") is not None:
                side = request.query["side"]
                if side not in {"pc", "phone"} or request.match_info.get("receipt") is None:
                    raise ValueError("Invalid backup side")
                result = {"history": result[side]}
            elif "local_before" in result:
                result = {key: value for key, value in result.items() if key != "local_before"}
        except LookupError:
            raise web.HTTPNotFound() from None
        except ValueError:
            raise web.HTTPBadRequest() from None
        return web.json_response(result)

    async def _sync_export(self, request):
        from hermes_state_errors import SessionActiveWriteGuardError
        from hermes_state_meu_sync import fingerprint

        session_id = request.match_info["session_id"] if self.sync_profile else self.sync_session
        scope = ({"profile_sync": True, "timestamps": True}
                 if self.sync_profile and request.query.get("timestamps") == "1"
                 else {"profile_sync": True} if self.sync_profile else {})
        try:
            if self.personal_space:
                scope['personal_space'] = self.personal_space
            history = await asyncio.to_thread(self.authority.db.export_meu_sync_history, session_id, **scope)
        except LookupError:
            raise web.HTTPNotFound() from None
        except SessionActiveWriteGuardError:
            return web.json_response({"status": "busy"}, status=409)
        except ValueError:
            raise web.HTTPConflict() from None
        return web.json_response({"history": history, "fingerprint": fingerprint(history)}
                                 if request.query.get("recovery") == "1" else history)

    async def _sync_apply(self, request):
        from hermes_state_errors import (
            CompressionSessionClosedError, SessionCompressionInProgressError, SessionTurnLeaseLostError,
        )

        history = await self._json(request)
        session_id = request.match_info["session_id"] if self.sync_profile else self.sync_session
        if history.get("id") != session_id:
            raise web.HTTPForbidden()
        scope = {"profile_sync": True} if self.sync_profile else {}
        if self.personal_space:
            scope['personal_space'] = self.personal_space
        try:
            async with self.lock:
                status = await asyncio.to_thread(self.authority.db.apply_meu_sync_history, history, **scope)
        except LookupError:
            raise web.HTTPNotFound() from None
        except ValueError:
            raise web.HTTPBadRequest() from None
        except (CompressionSessionClosedError, SessionCompressionInProgressError, SessionTurnLeaseLostError):
            return web.json_response({"status": "busy"}, status=409)
        return web.json_response({"status": status}, status=409 if status in {"conflict", "deleted"} else 200)

    async def _capabilities(self, _request):
        return web.json_response({"auth": {"required": True}, "features": {
            "run_submission": True, "run_status": True, "mobile_sessions": True,
            "runs_idempotency": {"pairing_session": True, "retention_seconds": self.session_seconds}}})

    async def _call(self, method, params):
        if self.connection is None:
            raise web.HTTPGone()
        result = await self.connection.dispatch({"id": "mobile", "method": method, "params": params})
        if not result or not isinstance(result.get("result"), dict):
            error = (result or {}).get("error", {})
            logger.warning("Mobile preview %s refused: %s", method, error.get("data", {}).get("reason", "unknown"))
            raise web.HTTPConflict()
        return result["result"]

    def _session_rows(self, session_id=None):
        from hermes_state_local import POLICY_PREFIX

        # The canonical creation receipt commits atomically with the session. Its server-generated
        # request namespace identifies phone sessions even after a new pairing or gateway restart.
        db = self.authority.db
        with db._read_ctx() as conn:
            rows = conn.execute("""
                SELECT s.id, s.title, s.started_at, (
                    SELECT substr(t.content, 1, 100)
                    FROM messages t
                    WHERE t.session_id = s.id AND t.role = 'user' AND t.active = 1
                    AND coalesce(t.display_kind, '') != 'hidden'
                    ORDER BY t.id LIMIT 1
                ) AS opening
                FROM sessions s JOIN state_meta m ON m.key = ? || s.id
                WHERE json_extract(CASE WHEN json_valid(m.value) THEN m.value ELSE '{}' END,
                                   '$.request_id') LIKE ?
                AND (? IS NULL OR s.id = ?)
                ORDER BY s.started_at DESC, s.id DESC
                LIMIT 50
                """, (POLICY_PREFIX, MOBILE_SESSION_PREFIX + "%", session_id, session_id)).fetchall()
        return [{"id": row["id"], "title": row["title"] or " ".join((row["opening"] or "").split()) or "New session",
                 "started_at": row["started_at"]} for row in rows]

    async def _owned_session(self, session_id):
        if not isinstance(session_id, str) or not SESSION_PATTERN.fullmatch(session_id):
            raise web.HTTPNotFound()
        rows = await asyncio.to_thread(self._session_rows, session_id)
        if not rows:
            raise web.HTTPNotFound()
        return rows[0]

    async def _create_session(self, key):
        session = await self._call("session.create", {
            "source": "gui", "request_id": MOBILE_SESSION_PREFIX + key, "toolsets": [],
            "ignore_rules": True, "run_budget": 120,
        })
        return await self._owned_session(session["session_id"])

    async def _list_sessions(self, _request):
        return web.json_response({"sessions": await asyncio.to_thread(self._session_rows)})

    async def _new_session(self, request):
        key = request.headers.get("Idempotency-Key", "")
        if not KEY_PATTERN.fullmatch(key):
            raise web.HTTPBadRequest()
        async with self.lock:
            row = await self._create_session(key)
        return web.json_response(row, status=201)

    async def _open_session(self, request):
        row = await self._owned_session(request.match_info["session_id"])
        fingerprint = await asyncio.to_thread(
            self.authority.db.conversation_revision, row["id"], include_ancestors=True,
        )
        revision = sha256(repr((row["title"], fingerprint)).encode()).hexdigest()
        if request.query.get("since") == revision:
            return web.json_response({"unchanged": True})
        async with self.lock:
            snapshot = await self._call("session.resume", {
                "session_id": row["id"], "display_projection": True,
            })
        transcript = snapshot.get("display_messages") or []
        text = [item for item in transcript if item.get("role") in {"user", "assistant"}
                and isinstance(item.get("text"), str) and item["text"].strip()]
        messages = [{"role": item["role"], "content": item["text"][:2500]} for item in text[-40:]]
        limited = len(text) > 40 or any(len(item["text"]) > 2500 for item in text[-40:])
        return web.json_response({**row, "messages": messages, "history_limited": limited, "revision": revision})

    async def _submit(self, request):
        body = await self._json(request)
        text = body.get("input")
        key = request.headers.get("Idempotency-Key", "")
        if (set(body) - {"input", "session_id"} or not isinstance(text, str)
                or not text.strip() or len(text) > 8000 or not KEY_PATTERN.fullmatch(key)):
            raise web.HTTPBadRequest()
        async with self.lock:
            requested_session = body.get("session_id")
            if isinstance(requested_session, str) and requested_session.startswith("local-"):
                session_id = (await self._owned_session(requested_session))["id"]
                if not self.connection or session_id not in self.connection.subscriptions:
                    await self._call("session.resume", {"session_id": session_id, "omit_messages": True})
            elif requested_session is None or (isinstance(requested_session, str)
                                               and requested_session.startswith("meu-android-")):
                # Older Android previews used a client-side ID for a single chat.
                if self.legacy_session is None:
                    self.legacy_session = (await self._create_session(self.legacy_request))["id"]
                session_id = self.legacy_session
            else:
                raise web.HTTPBadRequest()
            if key in self.runs:
                previous_session, previous, _ = self.runs[key]
                if previous_session != session_id or previous != text:
                    raise web.HTTPConflict()
            else:
                if len(self.runs) >= MAX_RUNS:
                    raise web.HTTPTooManyRequests()
                receipt = await self._call("prompt.submit", {
                    "session_id": session_id, "text": text, "input_id": key,
                })
                self.runs[key] = (session_id, text, receipt["admission_id"])
        return web.json_response({"run_id": f"run_{key}"}, status=202)

    async def _status(self, request):
        run_id = request.match_info["run_id"]
        run = self.runs.get(run_id.removeprefix("run_")) if run_id.startswith("run_") else None
        if run is None:
            raise web.HTTPNotFound()
        receipt = await self._call("prompt.receipt", {
            "session_id": run[0], "admission_id": run[2], "include_result": True,
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
