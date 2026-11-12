"""Phase 7 on the phone: view a roadmap and approve or reject ONE milestone over the real
``/meu/coding`` route, attributed to the pairing device, with the same integrity rules."""

from types import SimpleNamespace

import pytest

from tests.meu_coding.phase3_support import make_git_repo
from tests.meu_coding.phase7_support import GOAL, ROADMAP, ScriptedPlanner, planner_service


@pytest.mark.asyncio
async def test_phone_views_and_approves_a_single_milestone(tmp_path, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import meu_coding.service_registry as registry
    from gateway.mobile_coding import mount
    from gateway.mobile_preview import MobilePreview

    repo = make_git_repo(tmp_path)
    service = planner_service(tmp_path, ScriptedPlanner(ROADMAP))
    monkeypatch.setattr(registry, "service_for_home", lambda home: service)
    created = service.roadmap_create(GOAL, str(repo))
    app = web.Application()
    mount(app, SimpleNamespace(device_id="dev-7", authority=SimpleNamespace(profile_id=str(tmp_path)),
                               _json=MobilePreview._json))
    async with TestClient(TestServer(app)) as phone:
        async def call(payload, status=200):
            response = await phone.post("/meu/coding", json=payload)
            assert response.status == status, await response.text()
            return await response.json()

        listed = (await call({"op": "roadmap_list"}))["roadmaps"]
        assert listed[0]["project"] == "repo" and str(repo) not in str(listed)
        roadmap = (await call({"op": "roadmap_get", "roadmap_id": created["roadmap_id"]}))["roadmap"]
        assert roadmap["approve"] == ["m1"] and str(repo) not in str(roadmap)
        m1 = roadmap["milestones"][0]
        base = {"op": "milestone_approve", "roadmap_id": created["roadmap_id"], "milestone_id": "m1",
                "revision": roadmap["revision"]}
        await call({**base, "fingerprint": m1["fingerprint"]}, status=409)  # confirmed missing
        refused = await call({**base, "fingerprint": "0" * 64, "confirmed": True}, status=409)
        assert "changed after it was shown" in refused["reason"]
        await call({**base, "milestone_id": "m2", "fingerprint": roadmap["milestones"][1]["fingerprint"],
                    "confirmed": True}, status=409)
        done = (await call({**base, "fingerprint": m1["fingerprint"], "confirmed": True, "source": "desktop"}))
        assert done["roadmap"]["milestones"][0]["status"] == "IN_PROGRESS"
        replay = await call({**base, "fingerprint": m1["fingerprint"], "confirmed": True}, status=409)
        assert "not ready" in replay["reason"]
        await call({"op": "roadmap_get", "roadmap_id": "nope"}, status=409)
    events = service.roadmap_get(created["roadmap_id"])["events"]
    approved = [e for e in events if e["event"] == "milestone_approved"]
    assert len(approved) == 1 and approved[0]["source"] == "phone-dev-7"
