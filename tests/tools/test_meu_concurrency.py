"""The Meu gate limits actual concurrent model workers, including inline fallback."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

from tools.meu_limits import meu_child_slot
from tools import delegate_tool_config


def test_meu_two_concurrent_children_regardless_of_config(monkeypatch):
    monkeypatch.setenv("MEU_AGENT_MODE", "1")
    monkeypatch.setattr(delegate_tool_config, "_cfg", lambda: {"max_concurrent_children": 99})
    assert delegate_tool_config._get_max_concurrent_children() == 2


def test_meu_execution_gate_never_runs_three_children(monkeypatch):
    monkeypatch.setenv("MEU_AGENT_MODE", "1")
    lock = Lock()
    running = 0
    peak = 0

    def child():
        nonlocal running, peak
        with meu_child_slot():
            with lock:
                running += 1
                peak = max(peak, running)
            sleep(0.025)
            with lock:
                running -= 1

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: child(), range(6)))

    assert peak == 2
    assert running == 0
