"""``coding.remote.*`` through the validated JSON-RPC dispatcher: push, PR and merge each need
their own preview fingerprint and an explicit ``confirmed``; malformed or vague calls are
refused before reaching the service. Remote = local bare repository; GitHub = fake."""

import pytest

from tests.meu_coding.phase3_support import make_git_repo
from tests.meu_coding.phase6_support import bare, integrated, remote_service, with_remote
from tui_gateway import server


def _call(method, params):
    return server.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _ok(method, params):
    result = _call(method, params)
    assert "error" not in result, result
    return result["result"]


@pytest.fixture
def remote_rpc(tmp_path, monkeypatch):
    repo = make_git_repo(tmp_path)
    remote = with_remote(repo, tmp_path)
    service, hub = remote_service(tmp_path, remote)
    monkeypatch.setattr(server, "_coding_service", lambda: service)
    return integrated(service, repo)["task_id"], hub, remote


def test_rpc_push_pr_merge_each_with_its_own_approval(remote_rpc):
    task_id, hub, _remote = remote_rpc
    detected = _ok("coding.remote.detect", {"task_id": task_id})["task"]
    assert detected["remote"]["state"] == "ready_to_push" and detected["actions"]["push"]

    push = _ok("coding.remote.preview", {"task_id": task_id, "kind": "push"})["task"]["remote"]["push_preview"]
    wrong_kind = _call("coding.remote.approve", {"task_id": task_id, "kind": "merge",
                                                 "fingerprint": push["fingerprint"], "confirmed": True})
    assert wrong_kind["error"]["code"] == 5072
    _ok("coding.remote.approve", {"task_id": task_id, "kind": "push", "fingerprint": push["fingerprint"],
                                  "confirmed": True})
    pr = _ok("coding.remote.preview", {"task_id": task_id, "kind": "pr", "title": "Add add()"})["task"]
    pr = pr["remote"]["pr_preview"]
    _ok("coding.remote.approve", {"task_id": task_id, "kind": "pr", "fingerprint": pr["fingerprint"],
                                  "confirmed": True})
    status = _ok("coding.remote.refresh", {"task_id": task_id})["task"]["remote"]["pr_status"]
    assert status["state"] == "open" and not status["head_drift"]
    merge = _ok("coding.remote.preview", {"task_id": task_id, "kind": "merge", "method": "squash"})["task"]
    merge = merge["remote"]["merge_preview"]
    done = _ok("coding.remote.approve", {"task_id": task_id, "kind": "merge", "fingerprint": merge["fingerprint"],
                                         "confirmed": True})["task"]
    assert done["remote"]["state"] == "merged" and done["remote"]["merged"]["target_verified"]
    assert _ok("coding.remote.feedback", {"task_id": task_id})["comments"] == []
    assert hub.calls.count("create_pull") == 1


def test_rpc_remote_calls_are_strictly_validated(remote_rpc):
    task_id, hub, remote = remote_rpc
    bad = [
        ("coding.remote.approve", {"task_id": task_id, "kind": "push", "fingerprint": "abc", "confirmed": True}),
        ("coding.remote.approve", {"task_id": task_id, "kind": "push", "fingerprint": "0" * 64}),
        ("coding.remote.approve", {"task_id": task_id, "kind": "force_push", "fingerprint": "0" * 64,
                                   "confirmed": True}),
        ("coding.remote.approve", {"task_id": task_id, "kind": "push", "fingerprint": "0" * 64, "confirmed": True,
                                   "force": True}),
        ("coding.remote.preview", {"task_id": task_id, "kind": "push", "refspec": "+main:main"}),
        ("coding.remote.preview", {"task_id": task_id, "kind": "merge", "method": "octopus"}),
        ("coding.remote.repair", {"task_id": task_id, "comment_ids": []}),
    ]
    for method, params in bad:
        assert "error" in _call(method, params), (method, params)
    assert hub.calls == [] and bare(remote, "branch", "--list") == "* main"
