"""Human result decisions through the real registry/service, Git and pytest."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.tools.test_coding_task_tool import setup_chat, call
from tests.meu_coding.phase3_support import snapshot, git
from tools.coding_result_choice import KEEP, REJECT
from model_tools import handle_function_call

__all__ = ["setup_chat"]


def start(monkeypatch):
    monkeypatch.setattr("tools.coding_task_approval.ask_coding_approval", lambda view: "approve")
    result = call(description="Add add", files=["calc/ops.py", "tests/test_ops.py"])
    assert result["stage"] == "awaiting_keep_reject", result
    return result


def review(callback, session="chat-1", **args):
    return json.loads(handle_function_call("coding_task", {"action": "review_result", **args},
        task_id="chat-runtime", session_id=session, turn_id="review-turn", tool_call_id="review-call",
        parent_agent=SimpleNamespace(clarify_callback=callback)))


@pytest.mark.parametrize("choice,stage,decision", [(KEEP,"ready_to_commit","keep"),(REJECT,"rejected","reject_result")])
def test_human_choice_reaches_existing_service_and_survives_restart(setup_chat, monkeypatch, choice, stage, decision):
    repo, engine, _, factory = setup_chat
    before = snapshot(repo)
    view = start(monkeypatch)
    shown = []
    def answer(questions):
        shown.extend(questions)
        return {"answers": {questions[0]["qid"]: choice}, "outcome": "submitted"}
    result = review(answer, coding_task_id=view["task_id"])
    assert result["stage"] == stage, result
    assert shown and view["task_id"] in shown[0]["question"]
    assert shown[0]["qid"].startswith("coding-result:")
    assert "Αποτύπωμα αποτελέσματος" in shown[0]["question"]
    assert "Το αρχικό έργο παραμένει ανέπαφο" in shown[0]["question"]
    assert snapshot(repo) == before and git(repo, "status", "--porcelain") == ""
    record = engine.tasks[view["task_id"]]
    assert record.audit.decisions[-1]["decision"] == decision
    assert record.audit.decisions[-1]["source"] == "chat"
    assert not record.audit.commit_hash
    if choice == KEEP:
        assert Path(record.result.worktree_path).exists()
    else:
        assert result["cleanup"]["worktrees"]  # real retention/archive policy ran
    recovered = factory().chat_task("chat-1", view["task_id"])
    assert recovered["stage"] == stage and recovered["restored"]
    # A retry never asks again or flips the decision, including after recovery.
    before_decisions = list(record.audit.decisions)
    def forbidden(questions):
        raise AssertionError("duplicate review prompt")
    assert review(forbidden, coding_task_id=view["task_id"])["stage"] == stage
    assert record.audit.decisions == before_decisions


@pytest.mark.parametrize("outcome,answer", [("cancelled",KEEP),("timed_out",KEEP),("submitted",None),("submitted","keep")])
def test_cancel_timeout_empty_or_unrecognized_answer_preserves_result(setup_chat, monkeypatch, outcome, answer):
    repo, engine, _, _ = setup_chat
    view = start(monkeypatch)
    result = review(lambda q: {"answers": {q[0]["qid"]: answer}, "outcome": outcome})
    assert result["stage"] == "awaiting_keep_reject"
    assert Path(engine.tasks[view["task_id"]].result.worktree_path).exists()
    assert not engine.tasks[view["task_id"]].audit.keep_reject
    assert git(repo,"status","--porcelain") == ""


def test_no_callback_cannot_turn_model_arguments_into_human_authority(setup_chat, monkeypatch):
    start(monkeypatch)
    result = review(None, choice="keep", approved=True)
    assert result["stage"] == "awaiting_keep_reject"


def test_another_chat_never_gets_the_question_or_changes_the_result(setup_chat, monkeypatch):
    view = start(monkeypatch)
    def forbidden(q):
        raise AssertionError("foreign task disclosed")
    result = review(forbidden, session="other-chat", coding_task_id=view["task_id"])
    assert "another conversation" in result["error"]


@pytest.mark.parametrize("drift", ["record", "file"])
def test_changed_result_or_files_invalidates_the_open_question(setup_chat, monkeypatch, drift):
    _, engine, _, _ = setup_chat
    view = start(monkeypatch)
    record = engine.tasks[view["task_id"]]
    def answer(q):
        if drift == "record":
            record.result.reviewer_rationale = "changed while waiting"
        else:
            (Path(record.result.worktree_path)/"unreviewed.txt").write_text("human work\n")
        return {"answers": {q[0]["qid"]: REJECT}, "outcome": "submitted"}
    result = review(answer, coding_task_id=view["task_id"])
    assert "changed" in result["error"]
    assert record.stage.value == "awaiting_keep_reject" and not record.audit.keep_reject
    assert Path(record.result.worktree_path).exists()


def test_pending_result_can_be_reviewed_after_process_restart(setup_chat, monkeypatch):
    repo, _, _, factory = setup_chat
    view = start(monkeypatch)
    recovered = factory()
    monkeypatch.setattr("meu_coding.service_registry.current_service", lambda: recovered)
    result = review(lambda q: {"answers": {q[0]["qid"]: KEEP}, "outcome": "submitted"}, coding_task_id=view["task_id"])
    assert result["stage"] == "ready_to_commit" and result["restored"]
    assert git(repo,"status","--porcelain") == ""
