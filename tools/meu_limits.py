"""Meu-wide child execution gate. Count actual agent runs, not just queued jobs."""

from contextlib import contextmanager
import os
from threading import BoundedSemaphore

_MAX_MEU_CHILDREN = 2
_MEU_CHILD_SLOTS = BoundedSemaphore(_MAX_MEU_CHILDREN)


@contextmanager
def meu_child_slot():
    """Only two Meu child model runs may execute at once in this process.

    A third job waits for a slot even when the async pool falls back to
    synchronous execution. Non-Meu runtimes preserve upstream behavior.
    """
    if os.environ.get("MEU_AGENT_MODE") != "1":
        yield
        return
    with _MEU_CHILD_SLOTS:
        yield
