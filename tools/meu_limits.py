"""Meu-wide child execution gate. Count actual agent runs, not just queued jobs."""

from contextlib import contextmanager
import os
from threading import BoundedSemaphore

_MAX_MEU_CHILDREN = 2
_MEU_CHILD_SLOTS = BoundedSemaphore(_MAX_MEU_CHILDREN)


@contextmanager
def meu_child_slot(child=None):
    """Only two Meu child model runs may execute at once in this process.

    A third job waits for a slot even when the async pool falls back to
    synchronous execution. Non-Meu runtimes preserve upstream behavior.
    """
    if os.environ.get("MEU_AGENT_MODE") != "1":
        yield True
        return
    acquired = _MEU_CHILD_SLOTS.acquire(blocking=False)
    waited = not acquired
    try:
        while not acquired:
            if getattr(child, "_interrupt_requested", False) is True:
                yield False
                return
            acquired = _MEU_CHILD_SLOTS.acquire(timeout=0.1)
        # A permit and Stop may arrive together. The waiting child must not
        # start after cancellation, nor release a permit owned by another run.
        yield not (waited and getattr(child, "_interrupt_requested", False) is True)
    finally:
        if acquired:
            _MEU_CHILD_SLOTS.release()
