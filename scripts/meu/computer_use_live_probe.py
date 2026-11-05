"""Opt-in Windows benchmark using Meu's real backend on one owned fixture.

Measures the native backend, not model round trips or approval-dialog UX.
Only the window launched by this process is captured or given input.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def await_record(path, predicate, *, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            row = json.loads(path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.05)
            continue
        if predicate(row):
            return row
        time.sleep(0.05)
    raise TimeoutError(f"No fresh fixture record in {path.name}")


def benchmark(directory, target):
    from tools.computer_use.cua_backend import CuaDriverBackend
    backend = CuaDriverBackend(permission_mode="standard")
    measurements = []
    recorded_at = ""

    def timed(name, call):
        start = time.perf_counter()
        result = call()
        row = {"step": name, "elapsed_ms": round((time.perf_counter() - start) * 1000, 2)}
        if hasattr(result, "ok"):
            row.update({key: getattr(result, key) for key in ("ok", "effect", "verified", "path", "code")})
            if not result.ok:
                raise RuntimeError(asdict(result))
        measurements.append(row)
        return result

    def controls():
        capture = timed("capture", lambda: backend.capture(mode="ax", **target))
        names = {el.label: el.index for el in capture.elements}
        return tuple(names[label] for label in ("Meu probe input", "Record test value", "Clear test value"))

    def record(button):
        nonlocal recorded_at
        timed("click_record", lambda: backend.click(element=button))
        row = await_record(directory / "observed.json", lambda r: r["recorded_utc"] > recorded_at)
        recorded_at = row["recorded_utc"]
        if row["pid"] != target["pid"]:
            raise AssertionError("The observed result did not belong to the fixture")
        return row["value"]

    def input_round(text):
        edit, button, clear = controls()
        timed("click_clear", lambda: backend.click(element=clear))
        timed("click_input", lambda: backend.click(element=edit))
        timed("type", lambda: backend.type_text(text))
        if record(button) != text:
            raise AssertionError("The fixture did not observe the actual typed value")

    def hotkey(delivery_mode):
        edit, button, _ = controls()
        timed("click_input", lambda: backend.click(element=edit))
        timed(f"ctrl_a_{delivery_mode}", lambda: backend.key("CTRL+A", delivery_mode=delivery_mode))
        replacement = f"Replacement with {delivery_mode} shortcut"
        timed("type", lambda: backend.type_text(replacement))
        return record(button) == replacement

    try:
        backend.start()
        input_round("Meu warmup: Καλημέρα 123")
        measurements.clear()
        for iteration in range(5):
            input_round(f"Meu native probe {iteration}: Καλημέρα 123")
        summary = {}
        for name in {row["step"] for row in measurements}:
            values = [row["elapsed_ms"] for row in measurements if row["step"] == name]
            summary[name] = {"median_ms": round(statistics.median(values), 2), "max_ms": max(values)}
        background = hotkey("background")
        foreground = None if background else hotkey("foreground")
        return {"schema": 1, "scope": "native_backend_not_approval_ui", "warmup_rounds": 1,
                "verified_rounds": 5, "actual_unicode_input_verified": True,
                "ctrl_a_background_verified": background, "ctrl_a_foreground_verified": foreground,
                "summary": summary}
    finally:
        (directory / "measurements.json").write_text(json.dumps(measurements, indent=2), encoding="utf-8")
        backend.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="A fresh output directory")
    parser.add_argument("--driver", type=Path, required=True)
    args = parser.parse_args()
    pwsh = shutil.which("pwsh")
    if sys.platform != "win32" or not pwsh or not args.driver.is_file():
        parser.error("Real Windows, PowerShell 7 and an existing driver are required")
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    home = directory / "profile"
    home.mkdir()
    (home / "config.yaml").write_text("computer_use:\n  no_overlay: true\n  cua_telemetry: false\n", encoding="utf-8")
    os.environ.update(HERMES_HOME=str(home), HERMES_CUA_DRIVER_CMD=str(args.driver.resolve()),
                      CUA_DRIVER_RS_TELEMETRY_ENABLED="0")
    fixture = Path(__file__).with_name("computer-use-fixture.ps1").resolve()
    with (directory / "fixture.log").open("wb") as log:
        process = subprocess.Popen([pwsh, "-NoProfile", "-STA", "-File", str(fixture), "-Directory", str(directory)],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            target = await_record(directory / "ready.json", lambda r: r["pid"] == process.pid, timeout=15)
            result = benchmark(directory, target)
            (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2))
        finally:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
