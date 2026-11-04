"""Stdlib-only entry point inside the retained interpreter, launched with -I -S.

Never import editable-install .pth files or bootstrap against a changed checkout.
"""
from pathlib import Path
import json
import os
import runpy
import sys


def main() -> None:
    transaction = Path(sys.executable).resolve().parent.parent
    # pythonw has no console streams. Recovery/backup output stays in its private log.
    log = (transaction / "watch.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    record = json.loads((transaction / "transaction.json").read_text(encoding="utf-8-sig"))
    saved = json.loads((transaction / "resume.json").read_text(encoding="utf-8-sig"))
    os.environ.update(HERMES_HOME=record["home"], MEU_HOME=record["home"], MEU_AGENT_MODE="1")
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "HERMES_PYTHON", "HERMES_RUNTIME_DIR"):
        os.environ.pop(key, None)
    if saved.get("runtimeDirectory"):
        os.environ["HERMES_RUNTIME_DIR"] = saved["runtimeDirectory"]
    # Windows ships this module in runtime/Lib, and pythonw.exe beside python.exe.
    sys.path[:0] = ["\\\\?\\" + str(transaction / name) for name in (".", "source", "dependencies")]
    sys.argv = [str(transaction / "meu_update_watch.py"), "--transaction", str(transaction), "--resume"]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
