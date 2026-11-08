"""Profile-owned grants for browsing one user-selected transfer tree."""
from __future__ import annotations

import json
import asyncio
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

from fastapi import HTTPException

from hermes_cli.meu_transfer_paths import TransferDirectory, directory_identity, relative_parts

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
        directory_identity(root)
        root = root.resolve(strict=True)
        grant = {"path": str(root), "identity": list(directory_identity(root)), "id": uuid.uuid4().hex}
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
            if list(directory_identity(root)) != grant["identity"] or not root.is_dir():
                raise HTTPException(409, "The selected folder changed. Select it again on the PC.")
        except FileNotFoundError:
            raise HTTPException(409, "The selected PC folder is unavailable.") from None
        return root, grant["id"]

    def _directory(self, path, generation=None, expected=None):
        parts = relative_parts(path, filename)
        if parts and generation is None:
            raise HTTPException(400, "Refresh the shared folder before browsing.")
        root, generation = self.grant(generation)
        directory = TransferDirectory(root, parts)
        try:
            self.grant(generation)
            if directory.root_identity != directory_identity(root):
                raise HTTPException(409, "The shared folder changed. Refresh the file list.")
            directory.token = hashlib.sha256(json.dumps(
                [generation, path, directory.identity], separators=(",", ":"),
            ).encode()).hexdigest()
            if expected is not None and directory.token != expected:
                raise HTTPException(409, "The folder changed. Refresh the file list.")
            return directory, generation
        except BaseException:
            directory.close()
            raise

    def listing(self, path="", generation=None):
        if not self.db.get_meta(KEY):
            if path or generation is not None:
                self.grant(generation)
            return {"enabled": False}
        directory, generation = self._directory(path, generation)
        files, folders = [], []
        with directory, directory.entries() as entries:
            for entry in entries:
                try:
                    filename(entry.name)
                    item = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(item.st_mode) or getattr(item, "st_file_attributes", 0) & 0x400:
                        continue
                    if stat.S_ISREG(item.st_mode):
                        files.append({"name": entry.name, "size": item.st_size, "modified": item.st_mtime})
                    elif stat.S_ISDIR(item.st_mode):
                        folders.append({"name": entry.name, "path": "/".join([*directory.parts, entry.name])})
                except (HTTPException, OSError):
                    continue
                if len(files) + len(folders) >= 1000:
                    break
            directory.validate()
            self.grant(generation)
            return {"enabled": True, "browse": True, "folder": directory.path.name,
                    "directory": str(directory.path), "path": path, "directory_id": directory.token,
                    "root_id": generation, "maximum_bytes": MAX_BYTES,
                    "folders": sorted(folders, key=lambda item: item["name"].casefold()),
                    "files": sorted(files, key=lambda item: item["name"].casefold())}

    def upload(self, name: str, generation: str, path="", directory_id=None):
        name = filename(name)
        if path and directory_id is None:
            raise HTTPException(409, "Refresh the target folder before sending.")
        directory, _ = self._directory(path, generation, directory_id)
        try:
            if (directory.path / name).exists() or (directory.path / name).is_symlink():
                raise HTTPException(409, "A file with this name already exists. Rename it before sending.")
            return TransferUpload(self, directory, name, generation)
        except BaseException:
            directory.close()
            raise

    def open_download(self, name: str, generation: str, path="", directory_id=None):
        name = filename(name)
        if path and directory_id is None:
            raise HTTPException(409, "Refresh the target folder before downloading.")
        directory, _ = self._directory(path, generation, directory_id)
        with directory:
            return self._open_download(directory, name, generation)

    def _open_download(self, directory, name, generation):
        target = directory.path / name
        try:
            identity = directory_identity(target)
            if not target.is_file():
                raise HTTPException(400, "Only regular files can be transferred.")
            descriptor = directory.open_file(name, os.O_RDONLY)
            stream = os.fdopen(descriptor, "rb")
        except FileNotFoundError:
            raise HTTPException(404, "File no longer exists.") from None
        try:
            item = os.fstat(stream.fileno())
            self.grant(generation)
            directory.validate()
            if not stat.S_ISREG(item.st_mode) or (item.st_dev, item.st_ino) != identity:
                raise HTTPException(409, "File changed before download.")
            if item.st_size > MAX_BYTES:
                raise HTTPException(413, "File exceeds the transfer limit.")
            return stream, item.st_size
        except BaseException:
            stream.close()
            raise


class TransferUpload:
    def __init__(self, folder, directory, name, generation):
        self.folder, self.directory, self.name, self.generation = folder, directory, name, generation
        self.temporary = ".meu-transfer-" + uuid.uuid4().hex
        descriptor = directory.open_file(self.temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        self.stream = os.fdopen(descriptor, "wb")
        self.size = 0
        self.closed = False

    def write(self, chunk):
        self.folder.grant(self.generation)
        self.directory.validate()
        self.size += len(chunk)
        if self.size > MAX_BYTES:
            raise HTTPException(413, "File exceeds the transfer limit.")
        self.stream.write(chunk)

    def finish(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.folder.grant(self.generation)
        self.directory.validate()
        try:
            # An exclusive hard link publishes a complete file, never clobbers
            # a same-name file created after admission, on Windows and POSIX.
            self.directory.publish(self.temporary, self.name)
        except FileExistsError:
            raise HTTPException(409, "A file with this name already exists.") from None
        return {"name": self.name, "size": self.size}

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.stream.close()
        finally:
            try:
                self.directory.remove(self.temporary)
            finally:
                self.directory.close()
