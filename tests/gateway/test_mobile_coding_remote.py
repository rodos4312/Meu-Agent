"""Phase 6 on the phone: the real ``/meu/coding`` route shows the remote state and approves a
push / PR / merge the PC previewed — each by its exact fingerprint, attributed to the pairing
device, never to a body field. The phone cannot create previews."""

from types import SimpleNamespace

import pytest

from tests.meu_coding.phase6_support import bare, integrated, remote_service, with_remote
from tests.meu_coding.phase3_support import make_git_repo


@pytest.fixture
def phone_setup(tmp_path, monkeypatch):
    import meu_coding.service_registry as registry

    repo = make_git_repo(tmp_path)
    remote = with_remote(repo, tmp_path)
    service, hub = remote_service(tmp_path, remote)
    monkeypatch.setattr(registry, "service_for_home", lambda home: service)
    task_id = integrated(service, repo)["task_id"]
    return service, hub, remote, task_id


async def _phone(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.mobile_coding import mount
    from gateway.mobile_preview import MobilePreview

    app = web.Application()
    mount(app, SimpleNamespace(device_id="dev-42", authority=SimpleNamespace(profile_id=str(tmp_path)),
                               _json=MobilePreview._json))
    return TestClient(TestServer(app))


@pytest.mark.asyncio
async def test_phone_approves_push_pr_and_merge_with_exact_fingerprints(phone_setup, tmp_path):
    service, hub, remote, task_id = phone_setup
    async with await _phone(tmp_path) as phone:
        async def call(payload, status=200):
            response = await phone.post("/meu/coding", json=payload)
            assert response.status == status, await response.text()
            return await response.json()

        service.remote_preview(task_id, "push")
        view = (await call({"op": "get", "task_id": task_id}))["task"]
        remote_view = view["remote"]
        assert view["label"] == "Needs remote approval" and remote_view["approve"]["push"]
        push = remote_view["push_preview"]
        assert push["destination_branch"].startswith("hermes-subagent/") and len(push["new_sha"]) == 12
        assert str(remote) not in str(view)  # no host path / remote URL on the phone

        refused = await call({"op": "remote_approve", "task_id": task_id, "kind": "push",
                              "fingerprint": "0" * 64, "confirmed": True}, status=409)
        assert "changed after approval" in refused["reason"]
        await call({"op": "remote_approve", "task_id": task_id, "kind": "push", "fingerprint": push["fingerprint"],
                    "confirmed": False}, status=409)
        done = (await call({"op": "remote_approve", "task_id": task_id, "kind": "push",
                            "fingerprint": push["fingerprint"], "confirmed": True, "source": "desktop",
                            "device": "desktop"}))["task"]
        assert done["remote"]["state"] == "pr_ready"
        assert service.get(task_id)["remote"]["pushed"]["approved_by"] == "phone-dev-42"

        replay = await call({"op": "remote_approve", "task_id": task_id, "kind": "push",
                             "fingerprint": push["fingerprint"], "confirmed": True}, status=409)
        assert "already used" in replay["reason"]
        await call({"op": "remote_preview", "task_id": task_id, "kind": "pr"}, status=409)  # PC-only

        pr = service.remote_preview(task_id, "pr")["remote"]["pr_preview"]
        opened = (await call({"op": "remote_approve", "task_id": task_id, "kind": "pr",
                              "fingerprint": pr["fingerprint"], "confirmed": True}))["task"]
        assert opened["remote"]["pr"]["number"] == 1

        merge = service.remote_preview(task_id, "merge")["remote"]["merge_preview"]
        shown = (await call({"op": "get", "task_id": task_id}))["task"]["remote"]["merge_preview"]
        assert shown["pr_number"] == 1 and shown["status"] == "clean" and shown["fingerprint"] == merge["fingerprint"]
        assert shown["target_branch"] == "main" and "checks" in shown and "reviews" in shown
        merged = (await call({"op": "remote_approve", "task_id": task_id, "kind": "merge",
                              "fingerprint": merge["fingerprint"], "confirmed": True}))["task"]
        assert merged["remote"]["merged"]["target_verified"]
        assert bare(remote, "rev-parse", "main").startswith(merged["remote"]["merged"]["merge_commit"])

        refreshed = (await call({"op": "remote_refresh", "task_id": task_id}))["task"]
        assert refreshed["remote"]["pr_status"]["merged"] is True
    assert hub.calls.count("create_pull") == 1 and sum(c.startswith("merge:") for c in hub.calls) == 1
