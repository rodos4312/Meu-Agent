"""Profile-owned grants for a single user-selected, flat transfer folder."""
from __future__ import annotations

import json
import asyncio
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from fastapi import HTTPException

KEY = "meu.transfers.folder.v1"
MAX_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 256 * 1024


async def transfer_io(function, *args):
    """Drain an admitted disk operation before cancellation closes its handle."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def filename(value: str) -> str:
    from hermes_cli.web_routers.files import _is_sensitive_path

    if (not value or value.startswith(".") or value != value.strip() or value.endswith(".")
            or len(value.encode("utf-8")) > 240 or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
            or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
            or _is_sensitive_path(Path(value))):
        raise HTTPException(400, "Choose a regular document filename.")
    return value


def _identity(path: Path):
    item = path.lstat()
    if stat.S_ISLNK(item.st_mode) or getattr(item, "st_file_attributes", 0) & 0x400:
        raise HTTPException(403, "Linked folders and files are not shared.")
    return item.st_dev, item.st_ino


class TransferFolder:
    def __init__(self, authority):
        self.authority = authority
        self.db = authority.db

    def select(self, directory: str):
        if not directory:
            self.db.set_meta(KEY, "")
            return {"enabled": False}
        root = Path(directory).expanduser()
        if not root.is_absolute() or not root.is_dir() or root.parent == root:
            raise HTTPException(400, "Choose an existing folder on this computer.")
        _identity(root)
        root = root.resolve(strict=True)
        grant = {"path": str(root), "identity": list(_identity(root)), "id": uuid.uuid4().hex}
        self.db.set_meta(KEY, json.dumps(grant))
        return self.listing()

    def grant(self, expected: str | None = None):
        if getattr(self.authority, "retiring", False) or getattr(self.authority, "retired", False):
            raise HTTPException(410, "This connection is no longer available.")
        raw = self.db.get_meta(KEY)
        if not raw:
            raise HTTPException(409, "Select a transfer folder in Meu on the PC first.")
        grant = json.loads(raw)
        if expected is not None and expected != grant["id"]:
            raise HTTPException(409, "The shared folder changed. Refresh before transferring.")
        root = Path(grant["path"])
        try:
            if list(_identity(root)) != grant["identity"] or not root.is_dir():
                raise HTTPException(409, "The selected folder changed. Select it again on the PC.")
        except FileNotFoundError:
            raise HTTPException(409, "The selected PC folder is unavailable.") from None
        return root, grant["id"]

    def listing(self):
        if not self.db.get_meta(KEY):
            return {"enabled": False}
        root, generation = self.grant()
        entries = []
        for path in root.iterdir():
            try:
                filename(path.name)
                _identity(path)
                item = path.stat()
                if stat.S_ISREG(item.st_mode):
                    entries.append({"name": path.name, "size": item.st_size, "modified": item.st_mtime})
            except (HTTPException, FileNotFoundError):
                continue
            if len(entries) >= 1000:
                break
        self.grant(generation)
        return {"enabled": True, "folder": root.name, "directory": str(root), "root_id": generation,
                "maximum_bytes": MAX_BYTES, "files": sorted(entries, key=lambda item: item["name"].casefold())}

    def upload(self, name: str, generation: str):
        root, _ = self.grant(generation)
        target = root / filename(name)
        if target.exists() or target.is_symlink():
            raise HTTPException(409, "A file with this name already exists. Rename it before sending.")
        return TransferUpload(self, target, generation)

    def open_download(self, name: str, generation: str):
        root, _ = self.grant(generation)
        target = root / filename(name)
        try:
            identity = _identity(target)
            if not target.is_file():
                raise HTTPException(400, "Only regular files can be transferred.")
            descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            stream = os.fdopen(descriptor, "rb")
        except FileNotFoundError:
            raise HTTPException(404, "File no longer exists.") from None
        try:
            item = os.fstat(stream.fileno())
            self.grant(generation)
            if not stat.S_ISREG(item.st_mode) or (item.st_dev, item.st_ino) != identity:
                raise HTTPException(409, "File changed before download.")
            if item.st_size > MAX_BYTES:
                raise HTTPException(413, "File exceeds the transfer limit.")
            return stream, item.st_size
        except BaseException:
            stream.close()
            raise


class TransferUpload:
    def __init__(self, folder, target, generation):
        self.folder, self.target, self.generation = folder, target, generation
        fd, path = tempfile.mkstemp(prefix=".meu-transfer-", dir=target.parent)
        self.temporary = Path(path)
        self.stream = os.fdopen(fd, "wb")
        self.size = 0

    def write(self, chunk):
        self.folder.grant(self.generation)
        self.size += len(chunk)
        if self.size > MAX_BYTES:
            raise HTTPException(413, "File exceeds the transfer limit.")
        self.stream.write(chunk)

    def finish(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.folder.grant(self.generation)
        try:
            # An exclusive hard link publishes a complete file, never clobbers
            # a same-name file created after admission, on Windows and POSIX.
            os.link(self.temporary, self.target)
        except FileExistsError:
            raise HTTPException(409, "A file with this name already exists.") from None
        return {"name": self.target.name, "size": self.size}

    def close(self):
        try:
            self.stream.close()
        finally:
            self.temporary.unlink(missing_ok=True)
