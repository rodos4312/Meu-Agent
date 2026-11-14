"""Pending coding decisions must survive a refused backend retirement."""

import threading
from types import SimpleNamespace

from hermes_cli.backend_retirement import RetirementFence
from meu_coding import service_registry
from meu_coding.task_service import Stage


def test_pending_coding_decision_blocks_retirement_until_kept(monkeypatch):
    record = SimpleNamespace(lock=threading.RLock(), restored=False, stage=Stage.AWAITING_APPROVAL)
    service = SimpleNamespace(_lock=threading.Lock(), tasks={"task": record})
    monkeypatch.setattr(service_registry, "_services", {"profile-b": service})
    fence = RetirementFence()
    assert fence.prepare()["idle"] is False
    with fence.work() as admitted:
        assert admitted  # Refusal did not freeze the old runtime.
    record.stage = Stage.AWAITING_KEEP_REJECT
    assert fence.prepare()["idle"] is False
    record.stage = Stage.READY_TO_COMMIT
    prepared = fence.prepare()
    assert prepared["ok"] is True
    assert fence.commit(prepared["token"]) == {"ok": True}
    with fence.work() as admitted:
        assert not admitted
    assert record.stage == Stage.READY_TO_COMMIT


def test_unreadable_coding_ledger_fails_closed_without_starting_services(monkeypatch):
    service = SimpleNamespace(_lock=threading.Lock(), tasks={})
    monkeypatch.setattr(service_registry, "_services", {"profile-a": service})
    service._lock.acquire()
    try:
        assert RetirementFence().prepare()["idle"] is None
    finally:
        service._lock.release()
    assert RetirementFence().prepare()["ok"] is True
    monkeypatch.setattr(service_registry, "_services", {})
    assert RetirementFence().prepare()["ok"] is True
    assert not service_registry._services


def test_coding_worker_holds_admission_until_all_cleanup_has_finished(monkeypatch):
    import pytest
    from hermes_cli import backend_retirement
    from meu_coding.task_service import TaskError, spawn_in_context
    from tests.waiting import wait_until

    fence = RetirementFence()
    monkeypatch.setattr(backend_retirement, "retirement", fence)
    started, release = threading.Event(), threading.Event()

    def worker():
        started.set()
        assert release.wait(10)

    spawn_in_context(worker, "coding-retirement-test")
    try:
        assert started.wait(10)
        assert fence.prepare()["idle"] is False
    finally:
        release.set()
    assert wait_until(lambda: fence.active_count() == 0, timeout=10)
    permit = fence.prepare()
    assert fence.commit(permit["token"])["ok"] is True
    with pytest.raises(TaskError, match="restarting"):
        spawn_in_context(lambda: None, "must-not-start")
