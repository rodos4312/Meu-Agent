"""CI-only fault control: actual Windows handles, exact executable and creation time."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

def require_runner():
    if (os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != "rodos4312/Meu-Agent"):
        raise SystemExit("Fault control requires the disposable Meu Windows runner")


require_runner()

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]


def end_owned(pid, expected, since, created=None):
    handle = kernel.OpenProcess(0x100001 | 0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        image = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(image))
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        actual = ((times[0].dwHighDateTime << 32) + times[0].dwLowDateTime) / 10_000_000 - 11644473600
        if (os.path.normcase(os.path.realpath(image.value)) != os.path.normcase(os.path.realpath(expected))
                or actual < since or (created is not None and abs(created - actual) > 0.001)):
            raise ValueError("Fault target does not own the expected executable and creation time")
        if not kernel.TerminateProcess(handle, 83) or kernel.WaitForSingleObject(handle, 10000) != 0:
            raise RuntimeError("Owned fault target did not stop")
    finally:
        kernel.CloseHandle(handle)


def hold(file):
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(file, 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        print("LOCKED", flush=True)
        sys.stdin.read()
    finally:
        kernel.CloseHandle(handle)


action, location = sys.argv[1:3]
if action == "hold":
    hold(location)
else:
    transaction = Path(location)
    record = json.loads((transaction / "transaction.json").read_text(encoding="utf-8-sig"))
    if action == "guardian":
        end_owned(record["watcherPid"], record["watcherExecutable"], record["watcherCreated"], record["watcherCreated"])
    elif action == "installer":
        saved = json.loads((transaction / "resume.json").read_text(encoding="utf-8-sig"))
        end_owned(int(sys.argv[3]), record["nativeInstaller"], saved["parentCreated"])
    else:
        raise ValueError("Unknown private fault control action")
