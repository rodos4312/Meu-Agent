"""``coding.*`` through the validated JSON-RPC dispatcher: start → exact-fingerprint decision
(consumed once) → keep, with refusals as actionable 5072 errors."""

import pytest

from meu_coding.task_service import CodingTaskService, ModelBundle
from tests.meu_coding.phase3_support import TASK, ScriptedModel, fake_adapter, good, make_git_repo
from tui_gateway import server


def _call(method, params):
    return server.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _ok(method, params):
    result = _call(method, params)
    assert "error" not in result, result
    return result["result"]


@pytest.fixture
def coding(tmp_path, monkeypatch):
    service = CodingTaskService(
        models_factory=lambda: ModelBundle(None, ScriptedModel([good]), None, {"coder": "fake:strong"}, "test"),
        adapter_factory=fake_adapter, spawn=lambda fn, name: fn(), audit_directory=tmp_path / "audit")
    monkeypatch.setattr(server, "_coding_service", lambda: service)
    return make_git_repo(tmp_path), service


def test_rpc_flow_with_single_use_exact_decision(coding):
    repo, _service = coding
    task = _ok("coding.start", {"description": TASK.description, "project_root": str(repo),
                                "explicit_files": list(TASK.explicit_files)})["task"]
    assert task["stage"] == "awaiting_approval", task["error"]
    approval = task["approval"]
    decide = {"task_id": task["task_id"], "approval_id": approval["approval_id"], "decision": "approve",
              "device": "desktop-test"}

    wrong = _call("coding.decide", {**decide, "fingerprint": "0" * 64})
    assert wrong["error"]["code"] == 5072 and "approval required again" in wrong["error"]["message"]

    done = _ok("coding.decide", {**decide, "fingerprint": approval["fingerprint"]})["task"]
    assert done["stage"] == "awaiting_keep_reject" and "+def add" in done["execution"]["actual_diff"]

    replay = _call("coding.decide", {**decide, "fingerprint": approval["fingerprint"]})
    assert replay["error"]["code"] == 5072 and "already used" in replay["error"]["message"]

    kept = _ok("coding.keep", {"task_id": task["task_id"]})["task"]
    assert kept["stage"] == "ready_to_commit"
    assert [row["task_id"] for row in _ok("coding.list", {})["tasks"]] == [task["task_id"]]


def test_rpc_rejects_unknown_keys_and_malformed_decisions(coding):
    repo, _service = coding
    unknown = _call("coding.start", {"description": "x", "project_root": str(repo), "auto_approve": True})
    assert "error" in unknown
    short = _call("coding.decide", {"task_id": "t", "approval_id": "a", "fingerprint": "abc", "decision": "approve"})
    assert "error" in short
    vague = _call("coding.decide", {"task_id": "t", "approval_id": "a", "fingerprint": "0" * 64,
                                    "decision": "allow coding"})
    assert "error" in vague
    missing = _call("coding.get", {"task_id": "nope"})
    assert missing["error"]["code"] == 5072
    unconfirmed = _call("coding.commit.confirm", {"task_id": "nope", "message": "m", "token": "t"})
    assert "error" in unconfirmed  # ``confirmed`` is required, never defaulted
