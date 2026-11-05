"""Opaque HTTPS relay for the Meu companion. Run behind HTTPS on a trusted host."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import re
import secrets
import ssl

from aiohttp import WSMsgType, web

MAX_PACKET = 512 * 1024
MAX_ROOMS = 256
MAX_IN_FLIGHT = 4
ROOM = re.compile(r"[0-9a-f]{64}")
HOST_KEY = re.compile(r"[A-Za-z0-9_-]{43}")


class _Room:
    def __init__(self, socket):
        self.socket = socket
        self.pending = {}


def make_relay_app():
    rooms = {}

    async def host(request):
        room_id = request.match_info["room"]
        key = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not HOST_KEY.fullmatch(key) or sha256(key.encode()).hexdigest() != room_id:
            raise web.HTTPUnauthorized()
        if room_id in rooms:
            raise web.HTTPConflict()
        if len(rooms) >= MAX_ROOMS:
            raise web.HTTPServiceUnavailable()
        socket = web.WebSocketResponse(heartbeat=25, max_msg_size=MAX_PACKET + 16)
        room = _Room(socket)
        rooms[room_id] = room
        try:
            await socket.prepare(request)
            async for message in socket:
                if message.type != WSMsgType.BINARY or len(message.data) <= 16:
                    continue
                future = room.pending.get(message.data[:16])
                if future is not None and not future.done():
                    future.set_result(message.data[16:])
        finally:
            rooms.pop(room_id, None)
            for future in room.pending.values():
                if not future.done():
                    future.set_result(None)
        return socket

    async def exchange(request):
        room_id = request.match_info["room"]
        room = rooms.get(room_id) if ROOM.fullmatch(room_id) else None
        if room is None:
            raise web.HTTPServiceUnavailable()
        if request.content_type != "application/octet-stream":
            raise web.HTTPUnsupportedMediaType()
        packet = await request.read()
        if not 28 <= len(packet) <= MAX_PACKET or rooms.get(room_id) is not room:
            raise web.HTTPBadRequest()
        if len(room.pending) >= MAX_IN_FLIGHT:
            raise web.HTTPTooManyRequests()
        request_id = secrets.token_bytes(16)
        future = asyncio.get_running_loop().create_future()
        room.pending[request_id] = future
        try:
            await room.socket.send_bytes(request_id + packet)
            reply = await asyncio.wait_for(future, timeout=12)
        except (OSError, TimeoutError):
            raise web.HTTPGatewayTimeout() from None
        finally:
            room.pending.pop(request_id, None)
        if reply is None:
            raise web.HTTPServiceUnavailable()
        return web.Response(body=reply, content_type="application/octet-stream",
                            headers={"Cache-Control": "no-store"})

    async def close(_app):
        await asyncio.gather(*(room.socket.close() for room in list(rooms.values())))

    app = web.Application(client_max_size=MAX_PACKET + 1)
    app.add_routes([web.get("/v1/{room}/host", host, allow_head=False),
                    web.post("/v1/{room}/exchange", exchange)])
    app.on_shutdown.append(close)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    args = parser.parse_args()
    if bool(args.cert) != bool(args.key) or (not args.cert and args.host != "127.0.0.1"):
        parser.error("Use both --cert and --key for a public listener, or terminate HTTPS in a reverse proxy.")
    context = None
    if args.cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
    web.run_app(make_relay_app(), host=args.host, port=args.port, ssl_context=context, access_log=None)


if __name__ == "__main__":
    main()
