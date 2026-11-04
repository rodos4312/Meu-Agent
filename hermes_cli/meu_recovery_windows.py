"""Windows package-file preflight: refuse a foreign holder without killing it."""
from __future__ import annotations

import ctypes
from pathlib import Path
import threading
import time


def blocked_file(directory: Path) -> Path | None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    for file in directory.rglob("*"):
        if not file.is_file():
            continue
        if file.is_symlink() or not file.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Installed package contains a file outside its owned directory")
        # DELETE access tests replacement permission; nothing is changed/deleted.
        handle = kernel.CreateFileW(str(file), 0x10000, 7, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in (2, 3):
                continue  # The native installer can still be finishing its own cleanup.
            if error in (5, 32, 33):
                return file
            raise ctypes.WinError(error)
        kernel.CloseHandle(handle)
    return None


def wait_for_package(directory: Path, *, timeout: float = 60, wait=threading.Event().wait,
                     clock=time.monotonic, on_blocked=None) -> None:
    deadline = clock() + timeout
    while (blocked := blocked_file(directory)) is not None:
        if on_blocked is not None:
            on_blocked(blocked)
        if clock() >= deadline:
            raise TimeoutError("Meu package file is still locked: " + str(blocked))
        wait(min(1, max(0, deadline - clock())))
