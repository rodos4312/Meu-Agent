"""Closest end-to-end check without a phone: the desktop drives the real ``coding.*`` JSON-RPC
dispatcher, the "phone" drives the real ``/meu/coding`` aiohttp route of the pairing listener,
and both reach the same task authority on a real temporary repository.

start on desktop → approval on phone → phone approves → PC executes in a worktree → tests →
phone sees the result → phone keeps → desktop commits in the worktree → READY_TO_INTEGRATE.
No push, no merge; the project's target branch is untouched.
"""

from types import SimpleNamespace

import pytest

from tests.meu_coding.phase3_support import TASK, git, make_git_repo, snapshot
from tests.meu_coding.phase5_support import configure_identity, service_for
from tui_gateway import server


def _rpc(method, params):
    result = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert "error" not in result, result
    return result["result"]["task"]


@pytest.mark.asyncio
async def test_desktop_start_phone_approve_desktop_continue(tmp_path, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import meu_coding.service_registry as registry
    from gateway.mobile_coding import mount
    from gateway.mobile_preview import MobilePreview

    repo = make_git_repo(tmp_path)
    configure_identity(repo)
    service = service_for(tmp_path)
    monkeypatch.setattr(server, "_coding_service", lambda: service)
    monkeypatch.setattr(registry, "service_for_home", lambda home: service)
    before, head = snapshot(repo), git(repo, "rev-parse", "HEAD")

    desktop = _rpc("coding.start", {"description": TASK.description, "project_root": str(repo),
                                    "explicit_files": list(TASK.explicit_files)})
    assert desktop["stage"] == "awaiting_approval", desktop["error"]
    task_id = desktop["task_id"]

    app = web.Application()
    mount(app, SimpleNamespace(device_id="phone-1", authority=SimpleNamespace(profile_id=str(tmp_path)),
                               _json=MobilePreview._json))
    async with TestClient(TestServer(app)) as phone:
        async def call(payload):
            response = await phone.post("/meu/coding", json=payload)
            assert response.status == 200, await response.text()
            return await response.json()

        listed = await call({"op": "list"})
        assert [t["task_id"] for t in listed["tasks"]] == [task_id]
        pending = (await call({"op": "get", "task_id": task_id}))["task"]
        assert pending["label"] == "Needs your approval"
        assert pending["approval"]["fingerprint"] == desktop["approval"]["fingerprint"]

        approved = (await call({"op": "decide", "task_id": task_id, "decision": "approve",
                                "approval_id": pending["approval"]["approval_id"],
                                "fingerprint": pending["approval"]["fingerprint"]}))["task"]
        assert approved["stage"] == "awaiting_keep_reject" and approved["result"]["reviewer"]["verdict"] == "pass"
        assert all(t["status"] == "passed" for t in approved["result"]["tests"])

        after_phone = _rpc("coding.get", {"task_id": task_id})  # the desktop sees it at once
        assert after_phone["stage"] == "awaiting_keep_reject"
        assert after_phone["decisions"][0]["source"] == "mobile"

        kept = (await call({"op": "keep", "task_id": task_id}))["task"]
        assert kept["stage"] == "ready_to_commit" and not kept["actions"]["approve"]

    plan = _rpc("coding.commit.prepare", {"task_id": task_id})["commit"]
    done = _rpc("coding.commit.confirm", {"task_id": task_id, "message": "feat: add add()", "token": plan["token"],
                                          "confirmed": True})
    assert done["stage"] == "committed" and done["stage_label"] == "Ready to integrate"
    assert done["result"]["states"][-1] == "ready_to_integrate"
    assert snapshot(repo) == before and git(repo, "rev-parse", "HEAD") == head
    assert not git(repo, "remote").strip()
    assert [d["decision"] for d in done["decisions"]].count("approve") == 1  # executed once
