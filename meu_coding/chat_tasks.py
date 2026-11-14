"""Chat ownership and retry identity in the existing coding audit store."""
from __future__ import annotations

import hashlib
import os


class ChatTasksMixin:
    def start_chat(self, description: str, project_root: str, session_id: str,
                   request_id: str, explicit_files: tuple[str, ...] = ()) -> dict:
        from meu_coding.task_service import TaskError

        if not session_id or not request_id:
            raise TaskError("A trusted chat session and turn identity are required.")
        identity = hashlib.sha256((request_id + "\0" + os.path.normcase(os.path.realpath(project_root))
                                   + "\0" + description.strip()).encode()).hexdigest()
        with self._chat_lock:
            for record in self.tasks.values():
                if record.audit.chat_session_id == session_id and record.audit.chat_request_id == identity:
                    return self.get(record.task_id)
            return self.start(description, project_root, explicit_files,
                              chat_binding=(session_id, identity))

    def chat_task(self, session_id: str, task_id: str = "") -> dict:
        from meu_coding.task_service import TaskError

        if not session_id:
            raise TaskError("A trusted chat session identity is required.")
        with self._chat_lock:
            if task_id:
                record = self._require(task_id)
                if record.audit.chat_session_id != session_id:
                    raise TaskError("This coding task belongs to another conversation.")
            else:
                records = [r for r in self.tasks.values() if r.audit.chat_session_id == session_id]
                if not records:
                    raise TaskError("No coding task is associated with this conversation.")
                record = max(records, key=lambda r: r.audit.created_at)
            return self.get(record.task_id)


    def decide_chat_result(self, session_id: str, task_id: str, choice: str, fingerprint: str) -> dict:
        """Bind a human choice to this chat's exact reviewed result, under the task lock."""
        from meu_coding.task_service import TaskError
        from meu_coding.commit_flow import diff_digest
        from meu_coding.workspace import changed_files
        from tools.working_diff import collect_working_diff
        from tools.coding_result_choice import result_fingerprint

        view = self.chat_task(session_id, task_id)
        record = self._require(view["task_id"])
        with record.lock:
            view = self.get(view["task_id"])
            if view["stage"] in {"ready_to_commit", "kept", "rejected"}:
                return view
            if view["stage"] != "awaiting_keep_reject" or choice not in {"keep", "reject"}:
                raise TaskError("A result awaiting review and an explicit human choice are required.")
            if fingerprint != result_fingerprint(view):
                raise TaskError("The result changed while the question was open; review it again.")
            result = record.result
            diff = collect_working_diff(result.worktree_path, mode="all")
            files = changed_files(diff)
            if (not diff.get("success") or files != tuple(sorted(result.changed_files))
                    or diff_digest(diff.get("diff", ""), files) != result.reviewed_diff_digest):
                raise TaskError("The files changed after review; no result decision was applied.")
            return self.keep(task_id, source="chat") if choice == "keep" else self.reject(task_id, source="chat")
