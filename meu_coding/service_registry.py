"""One CodingTaskService per profile home, shared by every surface in the process.

The desktop RPC (``tui_gateway/methods_coding.py``) and the paired-phone transport
(``gateway/mobile_coding.py``) both resolve the service here, so a task has exactly one
authority: a decision from either device consumes the same approval object, and the other
device sees the result on its next read. Callers must already run inside the profile's
runtime scope (home, secrets, terminal policy).
"""

from __future__ import annotations

import os
import threading

_services: dict[str, object] = {}
_lock = threading.Lock()


def home_key(home: str) -> str:
    return os.path.normcase(os.path.realpath(str(home)))


def service_for_home(home: str):
    from meu_coding.task_service import CodingTaskService

    key = home_key(home)
    with _lock:
        service = _services.get(key)
        if service is None:
            service = CodingTaskService()
            _services[key] = service
        return service


def current_service():
    from hermes_constants import get_hermes_home

    return service_for_home(str(get_hermes_home()))


def live_task_count() -> int | None:
    """Read existing process-owned coding work; never restore/create a service for a probe."""
    from meu_coding.task_service import Stage

    terminal = {Stage.KEPT, Stage.READY_TO_COMMIT, Stage.COMMITTED, Stage.REJECTED,
                Stage.BLOCKED, Stage.FAILED, Stage.INTERRUPTED, Stage.INTEGRATED}
    if not _lock.acquire(blocking=False):
        return None
    try:
        services = list(_services.values())
    finally:
        _lock.release()
    count = 0
    for service in services:
        if not service._lock.acquire(blocking=False):
            return None
        try:
            records = list(service.tasks.values())
        finally:
            service._lock.release()
        for record in records:
            if not record.lock.acquire(blocking=False):
                return None
            try:
                if not record.restored and record.stage not in terminal:
                    count += 1
            finally:
                record.lock.release()
    return count
