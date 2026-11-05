"""Keep the project's OS lock until its native async completion unit settles."""
import json
from threading import RLock

from .projects import open_project


def run(args, parent_agent):
    from .project_tool import _home, _notes, _run

    owner = open_project(_home(parent_agent), args.get("project"))
    state = owner.__enter__()
    guard = RLock()
    closed = False

    def release(_answer=None):
        nonlocal closed
        with guard:
            if not closed:
                closed = True
                owner.__exit__(None, None, None)

    try:
        answer = _run(state, parent_agent, args.get("task_memory"), background=True,
                      on_batch_result=release, guard=guard) or {}
        with guard:
            summary = state.summary()
            summary["memory_notes"] = _notes(parent_agent, state.record["root"])
            if answer.get("status") == "dispatched":
                summary["dispatch"] = answer
            else:
                if answer.get("note"):
                    summary["execution_note"] = answer["note"]
                release()
            # Serialize while the checkpoint writer is excluded. Never save an old
            # snapshot after the worker releases its lease to another project run.
            return json.dumps(summary, ensure_ascii=False)
    except BaseException:
        release()
        raise
