"""Curated coding knowledge in MEU's EXISTING project memory (no second memory database).

Notes live as ordinary entries of the project's ``PROJECT.md`` through
``tools.memory_tool.load_on_disk_store(project_cwd=...)`` and ``MemoryStore.add("project", …)``,
so MEU's own limits, file locking, drift checks and injection/exfiltration scanning apply.
A coding note is one structured line::

    [meu-coding:KNOWN_BUG] <note> | files: a.py, b.py | symbols: f, C | source: task 1a2b3c4d

Nothing is saved automatically. The service PROPOSES candidates (note, category, source
task, confidence, why it matters); only a durable, secret-free, sufficiently confident
candidate the user accepts becomes a note. On retrieval the CURRENT repository wins: a note
naming a file or symbol that no longer exists is returned marked ``stale`` and never fed to
the Architect or Planner as truth.

The versioned deferred-work register ``docs/MEU_DEFERRED_WORK.md`` is read as well, so deferred
items (e.g. the 97 pre-existing desktop failures) are visible to the Planner without
anyone's personal memory.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

PREFIX = "[meu-coding:"
DEFERRED_REGISTER = "docs/MEU_DEFERRED_WORK.md"
MIN_CONFIDENCE = 0.6
MAX_NOTE = 300
_ENTRY = re.compile(r"^\[meu-coding:([A-Z_]+)\]\s*(.+?)(?:\s*\|\s*files:\s*([^|]*))?(?:\s*\|\s*symbols:\s*([^|]*))?"
                    r"(?:\s*\|\s*source:\s*([^|]*))?\s*$", re.DOTALL)
_LOG_LIKE = r"Traceback \(most recent|\b\d{1,2}:\d{2}:\d{2}\b|\bpid[ =]\d+|\b(DEBUG|INFO|WARNING|ERROR)\b:"
# no-tmp: ok — this pattern REJECTS memory notes that mention temp paths; it is not a scratch location
_TEMP_LIKE = r"|[A-Za-z]:\\Users\\[^\s]*\\Temp|/tmp/|\bthis (run|session)\b|\bjust now\b"
_TRANSIENT = re.compile(_LOG_LIKE + _TEMP_LIKE, re.IGNORECASE)
_PATH = re.compile(r"^[A-Za-z0-9_.\-/]+$")


class MemoryCategory(str, Enum):
    ARCHITECTURE_DECISION = "ARCHITECTURE_DECISION"
    PROJECT_CONVENTION = "PROJECT_CONVENTION"
    KNOWN_BUG = "KNOWN_BUG"
    FIX_HISTORY = "FIX_HISTORY"
    TEST_KNOWLEDGE = "TEST_KNOWLEDGE"
    RISK_NOTE = "RISK_NOTE"
    USER_PREFERENCE = "USER_PREFERENCE"
    DEFERRED_WORK = "DEFERRED_WORK"
    KNOWN_LIMITATION = "KNOWN_LIMITATION"


ALWAYS_RELEVANT = frozenset({MemoryCategory.DEFERRED_WORK, MemoryCategory.KNOWN_LIMITATION,
                             MemoryCategory.USER_PREFERENCE, MemoryCategory.PROJECT_CONVENTION})


class MemoryRefused(Exception):
    pass


@dataclass(frozen=True)
class MemoryCandidate:
    note: str
    category: str
    source_task: str
    confidence: float
    why: str
    files: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()

    @property
    def candidate_id(self) -> str:
        return hashlib.sha256(f"{self.category}\0{self.note}\0{self.source_task}".encode()).hexdigest()[:16]

    def entry(self) -> str:
        parts = [f"{PREFIX}{self.category}] {' '.join(self.note.split())}"]
        if self.files:
            parts.append("files: " + ", ".join(self.files))
        if self.symbols:
            parts.append("symbols: " + ", ".join(self.symbols))
        if self.source_task:
            parts.append(f"source: task {self.source_task[:8]}")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "candidate_id": self.candidate_id, "entry": self.entry()}


@dataclass
class MemoryNote:
    category: str
    note: str
    files: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    source: str = ""
    origin: str = "project_memory"  # "project_memory" | "repository"
    stale: bool = False
    stale_reason: str = ""
    relevance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(v.strip() for v in (value or "").split(",") if v.strip())


def parse_entry(entry: str) -> MemoryNote | None:
    match = _ENTRY.match(entry.strip())
    if not match or match.group(1) not in MemoryCategory.__members__:
        return None
    category, note, files, symbols, source = match.groups()
    return MemoryNote(category, note.strip(), _split(files), _split(symbols), (source or "").strip())


def check_candidate(candidate: MemoryCandidate) -> list[str]:
    """Why a candidate must not be saved (empty: it may be)."""
    from meu_coding.semantic_index import holds_secret
    from tools.memory_tool_store import _scan_memory_content

    problems = []
    if candidate.category not in MemoryCategory.__members__:
        problems.append("unknown category")
    note = " ".join(candidate.note.split())
    if not 15 <= len(note) <= MAX_NOTE:
        problems.append(f"a note is 15–{MAX_NOTE} characters")
    if candidate.confidence < MIN_CONFIDENCE:
        problems.append(f"confidence {candidate.confidence:.2f} is below {MIN_CONFIDENCE}")
    if _TRANSIENT.search(candidate.note):
        problems.append("looks transient (log line, timestamp, temp path or this-run detail)")
    text = candidate.entry()
    if holds_secret(text):
        problems.append("contains a credential or secret")
    threat = _scan_memory_content(text)
    if threat:
        problems.append(f"refused by MEU memory safety: {threat}")
    if any(not _PATH.match(f) or f.startswith("/") or ".." in f.split("/") for f in candidate.files):
        problems.append("file references must be repository-relative paths")
    return problems


def _repo_register(project_root: str) -> list[MemoryNote]:
    path = Path(project_root) / DEFERRED_REGISTER
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    notes = []
    for line in text.splitlines():
        match = re.match(r"^\s*-\s*\[([A-Z_]+)\]\s*(.+)$", line)
        if match and match.group(1) in MemoryCategory.__members__:
            notes.append(MemoryNote(match.group(1), match.group(2).strip(), source=DEFERRED_REGISTER,
                                    origin="repository"))
    return notes


def _default_store(project_root: str):
    from tools.memory_tool import load_on_disk_store

    return load_on_disk_store(project_cwd=project_root)


class CodingMemory:
    def __init__(self, store_factory: Callable[[str], Any] = _default_store) -> None:
        self.store_factory = store_factory

    def notes(self, project_root: str) -> list[MemoryNote]:
        store = self.store_factory(project_root)
        entries = store.project_entries if store.target_enabled("project") else []
        parsed = [n for n in (parse_entry(e) for e in entries) if n is not None]
        return parsed + _repo_register(project_root)

    def accept(self, project_root: str, candidate: MemoryCandidate) -> MemoryNote:
        problems = check_candidate(candidate)
        if problems:
            raise MemoryRefused("Not saved: " + "; ".join(problems))
        store = self.store_factory(project_root)
        if not store.target_enabled("project"):
            raise MemoryRefused("Project memory is not available for this folder.")
        entry = candidate.entry()
        if entry in store.project_entries:
            raise MemoryRefused("This note is already in project memory.")
        result = store.add("project", entry)
        if not result.get("success", False):
            raise MemoryRefused(str(result.get("error") or "Project memory refused the note.")[:300])
        return parse_entry(entry)

    def retrieve(self, project_root: str, query: str, analysis=None, graph=None) -> list[MemoryNote]:
        """Relevant notes, each checked against the CURRENT repository."""
        from meu_coding.relevance import split_words

        words = set(split_words(query))
        found = []
        for note in self.notes(project_root):
            mark_stale(note, analysis, graph)
            hits = sorted(words & set(split_words(note.note + " " + " ".join(note.files + note.symbols))))
            if hits:
                note.relevance.append("mentions " + ", ".join(hits[:5]))
            if MemoryCategory(note.category) in ALWAYS_RELEVANT:
                note.relevance.append(f"{note.category.lower().replace('_', ' ')} (always shown)")
            if note.relevance:
                found.append(note)
        return found

    def deferred_work(self, project_root: str) -> list[MemoryNote]:
        return [n for n in self.notes(project_root) if n.category == MemoryCategory.DEFERRED_WORK.value]


def mark_stale(note: MemoryNote, analysis=None, graph=None) -> MemoryNote:
    if analysis is not None:
        missing = [f for f in note.files if f not in analysis.files_by_path]
        if missing:
            note.stale, note.stale_reason = True, f"{', '.join(missing)} no longer exists — the repository wins"
            return note
    if graph is not None:
        gone = [s for s in note.symbols if not graph.lookup_symbol(s)]
        if gone:
            note.stale, note.stale_reason = True, f"symbol {', '.join(gone)} no longer exists — the repository wins"
    return note


def context_hints(notes: list[MemoryNote]) -> tuple[tuple[str, str], ...]:
    """Only current notes become (path, note) relevance hints."""
    return tuple((path, n.note) for n in notes if not n.stale for path in n.files)


def task_candidates(record) -> list[MemoryCandidate]:
    """Proposals from a finished task; the user decides. Only outcomes worth remembering."""
    out: list[MemoryCandidate] = []
    result = record.result
    stage = record.stage.value
    if result is None:
        return out
    files = tuple(result.changed_files[:6])
    if stage in ("committed", "integrated") and result.reviewer_verdict == "pass":
        out.append(MemoryCandidate(
            f"{record.task.description.strip().splitlines()[0][:160]} — done in {', '.join(files[:3])}",
            MemoryCategory.FIX_HISTORY.value, record.task_id, 0.7,
            "A reviewed, tested change; future tasks on these files start from it.", files))
    tests = [t for t in result.tests if t.get("status") == "passed" and t.get("check")]
    if tests:
        out.append(MemoryCandidate(f"Tests covering {', '.join(files[:3])}: {', '.join(t['check'] for t in tests[:3])}",
                                   MemoryCategory.TEST_KNOWLEDGE.value, record.task_id, 0.65,
                                   "Lets the Architect plan the right checks for these files.", files))
    return [c for c in out if not check_candidate(c)]
