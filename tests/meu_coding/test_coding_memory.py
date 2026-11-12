"""Phase 7 project memory: curated notes in MEU's EXISTING project memory, saved only on explicit
acceptance; transient or secret notes refused; stale notes detected and never fed as truth."""

import pytest

from meu_coding.coding_memory import (
    DEFERRED_REGISTER,
    CodingMemory,
    MemoryCandidate,
    MemoryRefused,
    check_candidate,
    context_hints,
    parse_entry,
)
from meu_coding.intelligence import RepositoryIntelligence
from tests.meu_coding.phase3_support import commit_all, make_git_repo


class FakeStore:
    def __init__(self, entries=None, enabled=True):
        self.project_entries = list(entries or [])
        self.enabled = enabled
        self.added = []

    def target_enabled(self, target):
        return self.enabled and target == "project"

    def add(self, target, content):
        self.added.append(content)
        self.project_entries.append(content)
        return {"success": True}


def _memory(store):
    return CodingMemory(lambda root: store)


def _candidate(**over):
    base = dict(note="calc.ops.sub must stay pure; callers rely on it having no side effects",
                category="ARCHITECTURE_DECISION", source_task="1a2b3c4d" * 4, confidence=0.8,
                why="prevents a regression", files=("calc/ops.py",), symbols=("sub",))
    base.update(over)
    return MemoryCandidate(**base)


@pytest.fixture
def repo(tmp_path):
    return make_git_repo(tmp_path)


def test_durable_note_is_saved_as_a_structured_project_memory_entry(repo):
    store = FakeStore()
    note = _memory(store).accept(str(repo), _candidate())
    assert store.added == ["[meu-coding:ARCHITECTURE_DECISION] calc.ops.sub must stay pure; callers rely on it "
                           "having no side effects | files: calc/ops.py | symbols: sub | source: task 1a2b3c4d"]
    assert note.category == "ARCHITECTURE_DECISION" and note.files == ("calc/ops.py",) and note.source == "task 1a2b3c4d"


@pytest.mark.parametrize("note", [
    "Traceback (most recent call last): File x.py line 3 in run",
    "ERROR: build failed at 12:31:07 while compiling the module",
    "in this run the tests passed against the fixture database",
])
def test_transient_notes_are_rejected(repo, note):
    store = FakeStore()
    with pytest.raises(MemoryRefused, match="transient"):
        _memory(store).accept(str(repo), _candidate(note=note))
    assert store.added == []


def test_low_confidence_unknown_category_and_bad_paths_are_rejected():
    assert any("confidence" in p for p in check_candidate(_candidate(confidence=0.3)))
    assert any("category" in p for p in check_candidate(_candidate(category="WHATEVER")))
    assert any("repository-relative" in p for p in check_candidate(_candidate(files=("/etc/passwd",))))
    assert any("repository-relative" in p for p in check_candidate(_candidate(files=("../x.py",))))


def test_secrets_are_never_stored(repo):
    store = FakeStore()
    for note in ("Use API key sk-abcdefghijklmnopqrstuvwxyz0123456789 for the staging server",
                 "deploy token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij is stored in the env file"):
        with pytest.raises(MemoryRefused, match="secret|safety"):
            _memory(store).accept(str(repo), _candidate(note=note))
    assert store.added == []


def test_stale_memory_is_detected_and_the_repository_wins(repo):
    store = FakeStore([_candidate().entry(),
                       _candidate(note="calc/legacy.py keeps the old rounding behaviour for exports",
                                  files=("calc/legacy.py",), symbols=()).entry(),
                       _candidate(note="the helper renamed_away handles negative inputs specially",
                                  files=(), symbols=("renamed_away",)).entry()])
    intel = RepositoryIntelligence(repo)
    intel.analyze_repository()
    notes = {n.note[:12]: n for n in _memory(store).retrieve(str(repo), "calc ops sub legacy helper negative",
                                                             intel.analysis, intel.graph)}
    assert not notes["calc.ops.sub"].stale
    assert notes["calc/legacy."].stale and "no longer exists" in notes["calc/legacy."].stale_reason
    assert notes["the helper r"].stale and "symbol renamed_away" in notes["the helper r"].stale_reason
    hints = context_hints(list(notes.values()))
    assert hints == (("calc/ops.py", notes["calc.ops.sub"].note),)  # stale notes never become hints


def test_deferred_work_comes_from_the_versioned_register(repo):
    (repo / DEFERRED_REGISTER).parent.mkdir(parents=True, exist_ok=True)
    (repo / DEFERRED_REGISTER).write_text("# Deferred\n\n- [DEFERRED_WORK] 97 pre-existing desktop failures wait "
                                          "for the hardening phase.\n- not a structured line\n", encoding="utf-8")
    commit_all(repo, "register")
    memory = _memory(FakeStore())
    deferred = memory.deferred_work(str(repo))
    assert [n.note for n in deferred] == ["97 pre-existing desktop failures wait for the hardening phase."]
    assert deferred[0].origin == "repository"
    retrieved = memory.retrieve(str(repo), "unrelated goal about payments")
    assert any(n.category == "DEFERRED_WORK" for n in retrieved)  # always visible to the planner


def test_unparseable_and_foreign_entries_are_ignored():
    assert parse_entry("User prefers tabs") is None
    assert parse_entry("[meu-coding:NOT_A_CATEGORY] x") is None
    assert parse_entry("[meu-coding:KNOWN_BUG] off-by-one in pagination | files: api/page.py").files == ("api/page.py",)


def test_task_history_candidate_is_linked_to_its_task(tmp_path):
    from tests.meu_coding.phase5_support import committed, service_for

    repo = make_git_repo(tmp_path)
    service = service_for(tmp_path)
    service.memory = _memory(FakeStore())
    view = committed(service, repo)
    candidates = service.memory_candidates(view["task_id"])
    fix = next(c for c in candidates if c["category"] == "FIX_HISTORY")
    assert fix["source_task"] == view["task_id"] and "calc/ops.py" in fix["files"] and fix["state"] == "proposed"
    service.memory_decide(view["task_id"], fix["candidate_id"], accept=True)
    assert service.memory.store_factory(None).added[0].endswith(f"source: task {view['task_id'][:8]}")
    assert next(c for c in service.memory_candidates(view["task_id"]) if c["candidate_id"] == fix["candidate_id"])[
        "state"] == "accepted"
    from meu_coding.task_service import TaskError

    with pytest.raises(TaskError, match="no longer available"):
        service.memory_decide(view["task_id"], fix["candidate_id"], accept=True)  # no double save


def test_memory_is_used_before_planning_and_recorded(tmp_path):
    from tests.meu_coding.phase5_support import service_for, start

    repo = make_git_repo(tmp_path)
    service = service_for(tmp_path)
    service.memory = _memory(FakeStore([_candidate().entry(),
                                        _candidate(note="calc/gone.py used to own add", files=("calc/gone.py",),
                                                   symbols=()).entry()]))
    view = start(service, repo)
    assert view["memory"]["used"][0]["files"] == ["calc/ops.py"]
    assert view["memory"]["stale_ignored"][0]["note"].startswith("calc/gone.py")
    assert service.tasks[view["task_id"]].task.context_hints == (("calc/ops.py", _candidate().note),)


def test_real_meu_project_memory_store_round_trip(tmp_path, monkeypatch):
    """E2E against MEU's MemoryStore in a temporary HERMES_HOME."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    repo = make_git_repo(tmp_path)
    memory = CodingMemory()
    memory.accept(str(repo), _candidate())
    notes = memory.notes(str(repo))
    assert [n.note for n in notes if n.origin == "project_memory"] == [_candidate().note]
    assert (home / "memories").is_dir()
