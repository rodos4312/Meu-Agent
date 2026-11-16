"""Seed/check actual state across an installed RC core update, in disposable CI only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("seed", "check"))
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args()
    home = args.home.resolve()
    if os.environ.get("GITHUB_ACTIONS") != "true" or not home.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve()):
        raise ValueError("This fixture is restricted to a disposable GitHub runner")
    os.environ["HERMES_HOME"] = str(home)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from hermes_state import SessionDB
    from gateway.mobile_spaces import PersonalDevices
    from pm.environments import selected_venv
    import yaml

    record = home.parent / "preservation.json"
    config = home / "config.yaml"
    project = home / "workspaces" / "existing-game" / "index.html"
    db = SessionDB(home / "state.db")
    try:
        devices = PersonalDevices(db)
        if args.mode == "seed":
            db.create_session("installer-preservation", "cli")
            db.append_message("installer-preservation", "user", "Keep my existing conversation")
            device, _ = devices.add_owner(SimpleNamespace(profile_id="default"), name="Owner", label="Existing phone")
            settings = yaml.safe_load(config.read_text(encoding="utf-8-sig")) or {}
            settings.setdefault("agent", {})["max_turns"] = 17
            config.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
            project.parent.mkdir(parents=True, exist_ok=True)
            project.write_text("<html>Existing project, keep this exact file</html>", encoding="utf-8")
            venv = selected_venv(home / "meu-agent")
            if venv is None:
                raise ValueError("The installed core must have its own selected dependency environment")
            record.write_text(json.dumps({"device": device["id"], "devices": db.get_meta("meu.personal-devices.v1"),
                "project": hashlib.sha256(project.read_bytes()).hexdigest(), "venv": str(venv)}), encoding="utf-8")
        else:
            expected = json.loads(record.read_text(encoding="utf-8-sig"))
            assert any(row["content"] == "Keep my existing conversation" for row in db.get_messages("installer-preservation"))
            assert db.get_meta("meu.personal-devices.v1") == expected["devices"]
            assert yaml.safe_load(config.read_text(encoding="utf-8-sig"))["agent"]["max_turns"] == 17
            assert hashlib.sha256(project.read_bytes()).hexdigest() == expected["project"]
            assert str(selected_venv(home / "meu-agent")) == expected["venv"]
            assert list((home / "backups").glob("meu-before-*.zip")), "Core upgrade must create its user-data backup"
            print("PASS: actual conversation, project, settings, devices and selected dependencies survived the core update")
    finally:
        db.close()


if __name__ == "__main__":
    main()
