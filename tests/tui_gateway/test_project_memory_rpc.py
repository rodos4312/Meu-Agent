"""Project notes through validated RPC, real per-profile files and restart."""

import json
import os
import subprocess
import sys

from tui_gateway import server
from tests.tui_gateway.test_projects_rpc import (
    _bind_profiles, _create_project, _profile_dir, _serving_launch_profile,
)


def _rpc(method, params):
    result = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert "error" not in result, result
    return result["result"]


def test_rpc_edits_are_profile_scoped(tmp_path, monkeypatch):
    launch = _profile_dir(tmp_path, "launch")
    other = _profile_dir(tmp_path, "other")
    folder = tmp_path / "project"
    folder.mkdir()
    _bind_profiles(monkeypatch, tmp_path, {"default": launch, "other": other})
    one = _create_project(launch, "One", folder)
    two = _create_project(other, "Two", folder)
    with _serving_launch_profile(launch):
        params = {"project_id": two["id"], "profile": "other"}
        initial = _rpc("projects.memory.get", params)
        assert initial["enabled"] and initial["entries"] == []
        written = _rpc("projects.memory.update", {**params, "action": "add", "revision": initial["revision"],
                                                   "content": "Export PNG in A5."})
        assert written["saved"], written
        assert _rpc("projects.memory.get", {"project_id": one["id"]})["entries"] == []
        stale = _rpc("projects.memory.update", {**params, "action": "add", "revision": initial["revision"],
                                                 "content": "Stale write must not land."})
        assert not stale["saved"] and stale["conflict"]
        oversized = _rpc("projects.memory.update", {**params, "action": "add", "revision": written["memory"]["revision"],
                                                     "content": "x" * 2500})
        assert not oversized["saved"]
        assert "Shorten a note" in oversized["error"]
        assert oversized["memory"]["revision"] == written["memory"]["revision"]
        latest = written["memory"]
        edited = _rpc("projects.memory.update", {**params, "action": "patch", "revision": latest["revision"],
                                                  "note_id": latest["entries"][0]["id"], "content": "Export PNG in A4."})
        assert edited["saved"], edited
        script = ("import json,sys; from tools.memory_tool import load_on_disk_store; "
                  "from tui_gateway.project_memory import snapshot; "
                  "print(json.dumps(snapshot(load_on_disk_store(project_cwd=sys.argv[1]))))")
        restarted = json.loads(subprocess.check_output([sys.executable, "-c", script, str(folder)],
                              env={**os.environ, "HERMES_HOME": str(other)}, text=True, encoding="utf-8"))
        assert restarted["entries"][0]["content"] == "Export PNG in A4."
        assert restarted["revision"] == edited["memory"]["revision"]
        removed = _rpc("projects.memory.update", {**params, "action": "remove", "revision": restarted["revision"],
                                                   "note_id": restarted["entries"][0]["id"]})
        assert removed["saved"] and removed["memory"]["entries"] == []
        refused = server.handle_request({"id": 1, "method": "projects.memory.get",
                                         "params": {**params, "project_id": "../../launch"}})
        assert "error" in refused


def test_rpc_respects_disabled_memory(tmp_path, monkeypatch):
    home = _profile_dir(tmp_path, "launch")
    folder = tmp_path / "project"
    folder.mkdir()
    _bind_profiles(monkeypatch, tmp_path, {"default": home})
    project = _create_project(home, "Project", folder)
    (home / "config.yaml").write_text("memory:\n  memory_enabled: false\n", encoding="utf-8")
    with _serving_launch_profile(home):
        params = {"project_id": project["id"]}
        assert not _rpc("projects.memory.get", params)["enabled"]
        result = server.handle_request({"id": 1, "method": "projects.memory.update", "params": {
            **params, "action": "add", "revision": "", "content": "Must stay disabled.",
        }})
        assert "error" in result
