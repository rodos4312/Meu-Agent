"""Phone coding approvals share the desktop's single task authority: exact, single-use,
device-attributed decisions, sanitized views, no duplicate execution, no remote actions."""

import json
import threading

import pytest

from gateway.mobile_coding import MOBILE_LABELS, diff_summary, operate
from meu_coding.task_service import TaskError
from tests.meu_coding.phase3_support import fake_runner, make_git_repo
from tests.meu_coding.phase5_support import service_for, start

PHONE = "a1b2c3"


@pytest.fixture
def setup(tmp_path):
    repo = make_git_repo(tmp_path)
    runner = fake_runner()
    return repo, service_for(tmp_path, runner=runner), runner


def _decide(service, view, device=PHONE, **overrides):
    approval = view["approval"]
    payload = {"op": "decide", "task_id": view["task_id"], "approval_id": approval["approval_id"],
               "fingerprint": approval["fingerprint"], "decision": "approve", **overrides}
    return operate(service, device, payload)


def test_pending_approval_appears_on_the_phone_with_the_exact_fingerprint(setup):
    repo, service, _ = setup
    desktop = start(service, repo)
    rows = operate(service, PHONE, {"op": "list"})["tasks"]
    assert rows[0]["task_id"] == desktop["task_id"] and rows[0]["label"] == MOBILE_LABELS["awaiting_approval"]
    phone = operate(service, PHONE, {"op": "get", "task_id": desktop["task_id"]})["task"]
    assert phone["approval"]["fingerprint"] == desktop["approval"]["fingerprint"]
    assert phone["approval"]["approval_id"] == desktop["approval"]["approval_id"]
    assert phone["project"] == repo.name and phone["files"] == ["calc/ops.py", "tests/test_ops.py"]
    assert phone["tests_expected"] and phone["risk"] and phone["pc"]["online"]
    assert phone["approval"]["proposed"]["files"][0]["additions"] >= 1
    assert str(repo) not in json.dumps(phone) and "\\\\" not in json.dumps(phone)  # no host paths


def test_phone_approval_needs_the_exact_proposal_and_syncs_the_desktop(setup):
    repo, service, _ = setup
    desktop = start(service, repo)
    with pytest.raises(TaskError, match="approval required again"):
        _decide(service, desktop, fingerprint="0" * 64)
    with pytest.raises(TaskError, match="approval required again"):
        _decide(service, desktop, approval_id="f" * 32)
    with pytest.raises(ValueError):
        _decide(service, desktop, fingerprint="not-hex")
    phone = _decide(service, desktop)["task"]
    assert phone["stage"] == "awaiting_keep_reject" and phone["result"]["reviewer"]["verdict"] == "pass"
    seen = service.get(desktop["task_id"])  # the desktop reads the same authority
    assert seen["stage"] == "awaiting_keep_reject"
    assert seen["decisions"][0] == {"decision": "approve", "source": "mobile", "device": "phone-" + PHONE,
                                    "at": seen["decisions"][0]["at"]}
    assert seen["result"]["approval_source"] == "mobile"


def test_desktop_rejection_invalidates_a_stale_phone_approval(setup):
    repo, service, runner = setup
    desktop = start(service, repo)
    service.decide(desktop["task_id"], approval_id=desktop["approval"]["approval_id"],
                   fingerprint=desktop["approval"]["fingerprint"], approve=False, approver="u", device="desktop")
    with pytest.raises(TaskError, match="already used"):
        _decide(service, desktop)
    assert runner.calls == []


def test_replayed_approval_and_cross_device_race_execute_once(setup):
    repo, service, runner = setup
    desktop = start(service, repo)
    outcomes, barrier = [], threading.Barrier(2)

    def attempt(decide):
        barrier.wait()
        try:
            decide()
            outcomes.append("ok")
        except TaskError:
            outcomes.append("refused")

    phone = threading.Thread(target=attempt, args=(lambda: _decide(service, desktop),))
    pc = threading.Thread(target=attempt, args=(lambda: service.decide(
        desktop["task_id"], approval_id=desktop["approval"]["approval_id"],
        fingerprint=desktop["approval"]["fingerprint"], approve=True, approver="u", device="desktop"),))
    phone.start(), pc.start()
    phone.join(), pc.join()
    assert sorted(outcomes) == ["ok", "refused"]
    assert len([d for d in service.get(desktop["task_id"])["decisions"] if d["decision"] == "approve"]) == 1
    calls = len(runner.calls)
    with pytest.raises(TaskError, match="already used"):
        _decide(service, desktop)  # replay
    assert len(runner.calls) == calls


def test_a_spoofed_device_or_source_in_the_body_is_ignored(setup):
    repo, service, _ = setup
    desktop = start(service, repo)
    _decide(service, desktop, device_id="desktop", source="desktop", approver="admin")
    decision = service.get(desktop["task_id"])["decisions"][0]
    assert decision["source"] == "mobile" and decision["device"] == "phone-" + PHONE


def test_keep_and_reject_from_the_phone_sync_and_stay_restricted(setup):
    repo, service, _ = setup
    first = start(service, repo)
    _decide(service, first)
    kept = operate(service, PHONE, {"op": "keep", "task_id": first["task_id"]})["task"]
    assert kept["stage"] == "ready_to_commit" and service.get(first["task_id"])["stage"] == "ready_to_commit"
    assert set(kept["actions"]) == {"approve", "reject_proposal", "keep", "reject"}  # no commit/integrate/push
    for op in ("commit", "integrate", "push", "merge", "start"):
        with pytest.raises((ValueError, TaskError)):
            operate(service, PHONE, {"op": op, "task_id": first["task_id"]})
    second = start(service, repo)
    _decide(service, second)
    rejected = operate(service, PHONE, {"op": "reject", "task_id": second["task_id"]})["task"]
    assert rejected["stage"] == "rejected" and service.get(second["task_id"])["stage"] == "rejected"


def test_offline_phone_finds_the_current_state_on_reconnect(setup):
    repo, service, _ = setup
    desktop = start(service, repo)
    # The phone is offline: nothing is decided for it, the approval simply stays pending.
    assert service.get(desktop["task_id"])["stage"] == "awaiting_approval"
    assert service.get(desktop["task_id"])["decisions"] == []
    service.decide(desktop["task_id"], approval_id=desktop["approval"]["approval_id"],
                   fingerprint=desktop["approval"]["fingerprint"], approve=True, approver="u", device="desktop")
    # Reconnecting shows what happened on the PC meanwhile, with the PC as the decision source.
    phone = operate(service, PHONE, {"op": "get", "task_id": desktop["task_id"]})["task"]
    assert phone["stage"] == "awaiting_keep_reject" and phone["decisions"][0]["source"] == "desktop"
    assert not phone["actions"]["approve"]


def test_opening_a_task_on_another_device_calls_no_model(setup):
    repo, service, _ = setup
    desktop = start(service, repo)
    coder = service.tasks[desktop["task_id"]].models.coding
    calls = len(coder.requests)
    for _ in range(3):
        operate(service, PHONE, {"op": "get", "task_id": desktop["task_id"]})
        operate(service, PHONE, {"op": "list"})
    assert len(coder.requests) == calls


def test_diff_summaries_are_capped_and_expand_per_file(setup):
    repo, service, _ = setup
    desktop = start(service, repo)
    expanded = operate(service, PHONE, {"op": "diff", "task_id": desktop["task_id"], "which": "proposed",
                                        "path": "calc/ops.py"})
    assert any(line.startswith("+def add") for line in expanded["lines"])
    big = "\n".join(["diff --git a/x.py b/x.py", "@@ -1 +1 @@"] + [f"+line {i}" for i in range(500)])
    summary = diff_summary(big)
    assert summary["truncated"] and len(summary["files"][0]["lines"]) == 40 and summary["files"][0]["additions"] == 500
    with pytest.raises(LookupError):
        operate(service, PHONE, {"op": "diff", "task_id": desktop["task_id"], "which": "proposed", "path": "../x"})
    with pytest.raises(ValueError):
        operate(service, PHONE, {"op": "get", "task_id": "../../etc"})


@pytest.mark.asyncio
async def test_route_uses_pairing_identity_and_profile_scope(setup, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import meu_coding.service_registry as registry
    from gateway.mobile_coding import mount
    from gateway.mobile_preview import MobilePreview

    repo, service, _ = setup
    desktop = start(service, repo)
    seen_homes = []

    def bound_service(home):
        from hermes_constants import get_hermes_home

        seen_homes.append((home, str(get_hermes_home())))
        return service

    monkeypatch.setattr(registry, "service_for_home", bound_service)
    preview = SimpleNamespace(device_id=PHONE, authority=SimpleNamespace(profile_id=str(tmp_path)),
                              _json=MobilePreview._json)
    app = web.Application()
    mount(app, preview)
    async with TestClient(TestServer(app)) as client:
        approval = desktop["approval"]
        response = await client.post("/meu/coding", json={
            "op": "decide", "task_id": desktop["task_id"], "approval_id": approval["approval_id"],
            "fingerprint": approval["fingerprint"], "decision": "approve", "device_id": "desktop"})
        assert response.status == 200, await response.text()
        replay = await client.post("/meu/coding", json={
            "op": "decide", "task_id": desktop["task_id"], "approval_id": approval["approval_id"],
            "fingerprint": approval["fingerprint"], "decision": "approve"})
        assert replay.status == 409 and "already used" in (await replay.json())["reason"]
    assert seen_homes and all(home == str(tmp_path) for home, _ in seen_homes)
    assert all(bound.lower() == str(tmp_path).lower() for _, bound in seen_homes)  # scope bound to the profile
    assert service.get(desktop["task_id"])["decisions"][0]["device"] == "phone-" + PHONE
