"""Project memory and intelligence observability of ``CodingTaskService`` (a mixin).

Before planning, current (non-stale) project memory becomes a discovery hint for the
relevance pipeline; stale notes are recorded as ignored, never used. After a task, the
service PROPOSES memory candidates; only the user's explicit acceptance saves one (through
MEU's existing project memory). The audit records which evidence shaped the context: ranking
components, semantic hits, memory hits, the model route and its reasons. Never contents or keys.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any

from meu_coding.coding_memory import MemoryRefused, context_hints, task_candidates

logger = logging.getLogger(__name__)


class MemoryMixin:
    def _apply_memory(self, record, intel) -> None:
        """Called under the project lock, after the index is current, before the Architect runs."""
        started = time.perf_counter()
        try:
            notes = self.memory.retrieve(record.project_root, record.task.description, intel.analysis, intel.graph)
        except Exception:  # memory is advisory: planning continues without it
            logger.warning("coding task %s: project memory unavailable", record.task_id, exc_info=True)
            notes = []
        hints = context_hints(notes)
        if hints:
            record.task = dataclasses.replace(record.task, context_hints=tuple(record.task.context_hints) + hints)
        record.memory = {
            "used": [{"category": n.category, "note": n.note[:200], "origin": n.origin, "files": list(n.files)}
                     for n in notes if not n.stale],
            "stale_ignored": [{"note": n.note[:200], "why": n.stale_reason} for n in notes if n.stale],
            "seconds": round(time.perf_counter() - started, 4)}
        record.audit.memory = {"used": len(record.memory["used"]), "stale_ignored": len(record.memory["stale_ignored"]),
                               "accepted": list(record.audit.memory.get("accepted", []))}

    def _record_intelligence(self, record, intel) -> None:
        semantic = intel.semantic.describe() if intel.semantic is not None else {"status": "off"}
        context = record.session.context if record.session else None
        record.intelligence = {
            "ranking": dict(intel.last_ranking),
            "semantic": {k: semantic.get(k) for k in ("status", "reason", "provider", "kind", "chunks",
                                                      "last_query_ms")},
            "memory_hits": len((record.memory or {}).get("used", [])),
            "context_items": len(context.bundle.items) if context else 0,
            "context_chars": sum(len(i.excerpt) for i in context.bundle.items) if context else 0,
            "milestone": dict(record.roadmap or {}),
            "repairs": len(record.session.attempts) if record.session else 0}
        record.audit.intelligence = dict(record.intelligence)

    # ── memory candidates (proposed; saved only on explicit acceptance) ──────

    def memory_candidates(self, task_id: str) -> list[dict[str, Any]]:
        record = self._require(task_id)
        dismissed = set((record.audit.memory or {}).get("dismissed", []))
        accepted = set((record.audit.memory or {}).get("accepted", []))
        return [dict(c.to_dict(), state="accepted" if c.candidate_id in accepted else "proposed")
                for c in task_candidates(record) if c.candidate_id not in dismissed]

    def memory_decide(self, task_id: str, candidate_id: str, *, accept: bool, source: str = "desktop") -> dict[str, Any]:
        from meu_coding.task_service import TaskError

        record = self._require(task_id)
        with record.lock:
            candidate = next((c for c in task_candidates(record) if c.candidate_id == candidate_id), None)
            memory = record.audit.memory = dict(record.audit.memory or {})
            if candidate is None or candidate_id in memory.get("accepted", []) + memory.get("dismissed", []):
                raise TaskError("This memory candidate is no longer available.")
            if accept:
                try:
                    self.memory.accept(record.project_root, candidate)
                except MemoryRefused as exc:
                    raise TaskError(str(exc)) from None
                memory["accepted"] = [*memory.get("accepted", []), candidate_id]
            else:
                memory["dismissed"] = [*memory.get("dismissed", []), candidate_id]
            record.audit.decisions.append({"decision": "memory_accept" if accept else "memory_dismiss",
                                           "source": source, "at": round(time.time(), 3)})
            self._save(record)
        return self.get(task_id)

    # ── semantic status (no indexing triggered by a status read) ────────────

    def semantic_status(self, project_root: str) -> dict[str, Any]:
        from meu_coding.workspace import WorkspaceError, read_identity

        try:
            root = read_identity(project_root).root
        except WorkspaceError:
            return {"status": "unavailable", "reason": "Not a git repository."}
        intel = self._intel.get(root)
        if intel is not None and intel.semantic is not None:
            return intel.semantic.describe()
        from hermes_cli.config import load_config_readonly

        from meu_coding.embeddings import resolve_embedding_provider

        choice = resolve_embedding_provider(load_config_readonly() or {})
        return {"status": choice.status if choice.provider is None else "not_indexed", "reason": choice.reason}
