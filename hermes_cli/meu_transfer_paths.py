"""Pinned directories for transfers confined to the PC-selected tree."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import stat

from fastapi import HTTPException


def directory_identity(path: Path):
    item = path.lstat()
    if stat.S_ISLNK(item.st_mode) or getattr(item, 'st_file_attributes', 0) & 0x400:
        raise HTTPException(403, 'Linked folders and files are not shared.')
    return item.st_dev, item.st_ino


def relative_parts(value, validate):
    if not isinstance(value, str) or len(value.encode('utf-8')) > 2048:
        raise HTTPException(400, 'Choose a folder inside the shared folder.')
    parts = value.split('/') if value else []
    if len(parts) > 32:
        raise HTTPException(400, 'The folder is too deeply nested.')
    return [validate(part) for part in parts]


def _windows_directory(path):
    import ctypes
    import msvcrt

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    # No FILE_SHARE_DELETE: ancestors cannot be renamed or replaced while held.
    handle = kernel.CreateFileW(str(path), 0x80, 3, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    try:
        item = os.fstat(fd)
        if not stat.S_ISDIR(item.st_mode) or getattr(item, 'st_file_attributes', 0) & 0x400:
            raise HTTPException(403, 'Linked folders are not shared.')
        return fd
    except BaseException:
        os.close(fd)
        raise


class TransferDirectory:
    def __init__(self, root, parts):
        self.path = root.joinpath(*parts)
        self.parts = parts
        self._stack = contextlib.ExitStack()
        self._paths = []
        try:
            self.fd = self._open(root, None)
            self.root_identity = self.identity
            for part in parts:
                self.fd = self._open(self._paths[-1][0] / part, self.fd)
        except (OSError, HTTPException) as error:
            self.close()
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(409, 'The folder is unavailable. Refresh the file list.') from None

    def _open(self, path, parent):
        if os.name == 'nt':
            if parent is None:
                for ancestor in reversed(path.parents):
                    fd = _windows_directory(ancestor)
                    self._stack.callback(os.close, fd)
            fd = _windows_directory(path)
        else:
            fd = os.open(path if parent is None else path.name,
                         os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        self._stack.callback(os.close, fd)
        item = os.fstat(fd)
        identity = item.st_dev, item.st_ino
        if (not stat.S_ISDIR(item.st_mode) or getattr(item, 'st_file_attributes', 0) & 0x400
                or identity != directory_identity(path)):
            raise HTTPException(403, 'Only regular shared folders are available.')
        self.identity = identity
        self._paths.append((path, identity))
        return fd

    def validate(self):
        try:
            if any(directory_identity(path) != identity for path, identity in self._paths):
                raise HTTPException(409, 'The folder changed. Refresh the file list.')
        except OSError:
            raise HTTPException(409, 'The folder is unavailable. Refresh the file list.') from None

    def entries(self):
        return os.scandir(self.path if os.name == 'nt' else self.fd)

    def open_file(self, name, flags):
        flags |= getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        if os.name == 'nt':
            return os.open(self.path / name, flags, 0o600)
        return os.open(name, flags, 0o600, dir_fd=self.fd)

    def mkdir(self, name):
        """Create one child exclusively while its selected parent stays pinned."""
        self.validate()
        if os.name == 'nt':
            os.mkdir(self.path / name, mode=0o700)
        else:
            os.mkdir(name, mode=0o700, dir_fd=self.fd)
        self.validate()

    def publish(self, temporary, name):
        if os.name == 'nt':
            os.link(self.path / temporary, self.path / name)
        else:
            os.link(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)

    def remove(self, name):
        if os.name == 'nt':
            (self.path / name).unlink(missing_ok=True)
        else:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=self.fd)

    def close(self):
        self._stack.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
