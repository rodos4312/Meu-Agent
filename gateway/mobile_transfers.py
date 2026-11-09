"""Same folder grant over the existing certificate-pinned phone pairing."""
import asyncio
from urllib.parse import quote

from aiohttp import web
from fastapi import HTTPException

from hermes_cli.meu_transfers import CHUNK_BYTES, MAX_BYTES, transfer_io


def mount(app, preview):
    def folder():
        from hermes_cli.meu_transfer_spaces import MobileTransferFolder
        return MobileTransferFolder(preview)

    async def listing(request):
        try:
            return web.json_response(await asyncio.to_thread(
                folder().listing, request.query.get("path", ""), request.query.get("root_id")))
        except HTTPException as error:
            return web.json_response({"detail": error.detail}, status=error.status_code)

    async def upload(request):
        writer = None
        try:
            if request.content_length is not None and request.content_length > MAX_BYTES:
                raise HTTPException(413, "File exceeds the transfer limit.")
            writer = folder().upload(request.query.get("name", ""), request.query.get("root_id", ""),
                                     request.query.get("path", ""), request.query.get("directory_id"))
            async for chunk in request.content.iter_chunked(CHUNK_BYTES):
                await transfer_io(writer.write, chunk)
            return web.json_response(await transfer_io(writer.finish))
        except HTTPException as error:
            return web.json_response({"detail": error.detail}, status=error.status_code)
        finally:
            if writer:
                writer.close()

    async def download(request):
        stream = None
        generation = request.query.get("root_id", "")
        name = request.query.get("name", "")
        source = folder()
        try:
            stream, size = source.open_download(name, generation, request.query.get("path", ""),
                                                request.query.get("directory_id"))
            response = web.StreamResponse(headers={
                "Content-Type": "application/octet-stream", "Content-Length": str(size),
                "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name), "Cache-Control": "no-store",
            })
            await response.prepare(request)
            while chunk := await transfer_io(stream.read, CHUNK_BYTES):
                source.grant(generation)
                await response.write(chunk)
            await response.write_eof()
            return response
        except HTTPException as error:
            if stream is not None:
                raise  # streaming already started: never return a successful truncated file
            return web.json_response({"detail": error.detail}, status=error.status_code)
        finally:
            if stream:
                stream.close()

    app.router.add_get("/meu/transfers", listing, allow_head=False)
    app.router.add_post("/meu/transfers/upload", upload)
    app.router.add_get("/meu/transfers/download", download, allow_head=False)
    # Native Android uses the same Dashboard file client as connected-PC mode.
    app.router.add_get("/api/meu-transfers", listing, allow_head=False)
    app.router.add_post("/api/meu-transfers/upload", upload)
    app.router.add_get("/api/meu-transfers/download", download, allow_head=False)
