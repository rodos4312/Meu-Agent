"""Phase 8 upgrade safety: state written by earlier Coding Engine versions (Phase 4–7 shapes)
loads under the current code without loss, without resuming anything, and without secrets.

Everything runs in a temporary HERMES_HOME; no real profile is touched."""

import json
import logging
import sqlite3
import uuid

import pytest

from meu_coding.coding_memory import CodingMemory, MemoryCandidate
from meu_coding.semantic_index import SCHEMA_VERSION, SemanticIndex
from tests.meu_coding.phase3_support import make_git_repo
from tests.meu_coding.phase5_support import service_for
from tests.meu_coding.phase7_support import ConceptEmbeddings, GOAL, ROADMAP, ScriptedPlanner, planner_service

FAKE_KEY = "sk-test-" + "Z" * 40  # a fake credential that must never surface anywhere


def _write_audit(folder, task_id, **fields):
    folder.mkdir(parents=True, exist_ok=True)
    base = {"task_id": task_id, "project": "/old/project", "description": "old task", "created_at": 1_700_000_000.0,
            "stages": [{"stage": "analyzing", "at": 1}], "models": {"coder": "fake:strong"}, "decisions": []}
    base.update(fields)
    (folder / f"{task_id}.json").write_text(json.dumps(base), encoding="utf-8")


def test_phase4_audit_without_later_fields_restores_without_resuming(tmp_path):
    folder = tmp_path / "audit"
    ids = {stage: uuid.uuid4().hex for stage in ("awaiting_approval", "executing", "awaiting_keep_reject",
                                                 "ready_to_commit", "committed", "planning")}
    for stage, task_id in ids.items():
        _write_audit(folder, task_id, stages=[{"stage": "analyzing", "at": 1}, {"stage": stage, "at": 2}])
    service = service_for(tmp_path)
    stages = {stage: service.get(task_id)["stage"] for stage, task_id in ids.items()}
    assert stages == {"awaiting_approval": "awaiting_approval", "executing": "interrupted",
                      "awaiting_keep_reject": "awaiting_keep_reject", "ready_to_commit": "ready_to_commit",
                      "committed": "committed", "planning": "failed"}
    expired = service.get(ids["awaiting_approval"])
    assert not expired["actions"]["approve"] and expired["actions"]["reject"]  # nothing can execute
    assert service.get(ids["executing"])["actions"]["reject"] and not service.get(ids["executing"])["busy"]
    for task_id in ids.values():
        view = service.get(task_id)
        assert view["remote"] is None or view["remote"]["state"] in ("not_checked", "unavailable")
        assert view["intelligence"] is None and view["roadmap"] is None


def test_phase6_remote_history_survives_and_never_re_pushes(tmp_path):
    folder = tmp_path / "audit"
    task_id = uuid.uuid4().hex
    _write_audit(folder, task_id, stages=[{"stage": "integrated", "at": 2}],
                 integration={"branch": "hermes-subagent/x", "review": {"verdict": "pass"}},
                 remote={"pushed": {"remote_sha": "a" * 40, "destination_branch": "hermes-subagent/x"},
                         "pr": {"number": 7, "source_sha": "a" * 40, "url": "https://example.invalid/7"},
                         "events": [{"event": "pushed", "at": 1}, {"event": "pr_created", "at": 2}]})
    service = service_for(tmp_path)
    view = service.get(task_id)
    assert view["remote"]["pr"]["number"] == 7 and view["remote"]["pending"] == []
    assert not view["actions"]["push"] and not view["actions"]["push_approve"]
    from meu_coding.task_service import TaskError

    with pytest.raises(TaskError):
        service.remote_approve(task_id, "push", fingerprint="0" * 64, confirmed=True)
    with pytest.raises(TaskError, match="never deletes branches"):
        service.reject(task_id)


def test_phase7_roadmap_without_optional_fields_loads(tmp_path):
    repo = make_git_repo(tmp_path)
    service = planner_service(tmp_path, ScriptedPlanner(ROADMAP))
    view = service.roadmap_create(GOAL, str(repo))
    path = tmp_path / "coding_roadmaps" / f"{view['roadmap_id']}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("context_summary", "pending_revision", "events", "error"):
        data.pop(key, None)
    for milestone in data["milestones"]:
        milestone.pop("note", None)
        milestone.pop("outcome", None)
    path.write_text(json.dumps(data), encoding="utf-8")
    reloaded = planner_service(tmp_path, ScriptedPlanner(ROADMAP)).roadmap_get(view["roadmap_id"])
    assert [m["fingerprint"] for m in reloaded["milestones"]] == [m["fingerprint"] for m in view["milestones"]]
    assert reloaded["actions"]["approve"] == ["m1"]


def test_semantic_store_from_an_older_schema_is_rebuilt_not_crashed(tmp_path, make_repo):
    store = tmp_path / "old.sqlite"
    db = sqlite3.connect(store)
    db.executescript("CREATE TABLE files (path TEXT PRIMARY KEY, source_hash TEXT, provider_key TEXT, chunking TEXT);"
                     "INSERT INTO files VALUES ('a.py', 'x', 'k', 'chunks-v1');")
    db.commit()
    db.close()
    root = make_repo({"a.py": "def reconnect_link(session):\n    '''retry with backoff'''\n    return session\n"})
    index = SemanticIndex(str(root), ConceptEmbeddings(), store)
    row = index._db.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
    assert row == (SCHEMA_VERSION,) and index.counts()["files"] == 0  # derived data rebuilt from scratch
    from meu_coding.intelligence import RepositoryIntelligence
    from meu_coding.semantic_index import SemanticLayer

    RepositoryIntelligence(root, semantic=SemanticLayer(index, "enabled", "t")).analyze_repository()
    assert [c["symbol"] for c in index.chunks_for("a.py")] == ["reconnect_link"]


def test_profile_upgrade_preserves_settings_memory_and_never_logs_secrets(tmp_path, monkeypatch, caplog):
    """A whole profile from before the Coding Engine: config with workload routes, a fake key in
    .env, existing project notes. The current engine reads all of it and leaks nothing."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "model:\n  provider: deepseek\n  default: deepseek-main\n"
        "smart_model_routing:\n  routes:\n    complex:\n      provider: deepseek\n      model: deepseek-pro-x\n",
        encoding="utf-8")
    (home / ".env").write_text(f"DEEPSEEK_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    repo = make_git_repo(tmp_path)
    memory = CodingMemory()
    store = memory.store_factory(str(repo))
    store.add("project", "The user prefers small, reviewed changes in this project.")  # a pre-existing plain note
    caplog.set_level(logging.DEBUG)

    from hermes_cli.config import load_config_readonly
    from meu_coding.routing_policy import resolve_workloads

    routes = resolve_workloads(load_config_readonly())
    assert routes["coding.planner"].model == "deepseek-pro-x" and routes["coding.review"].model == "deepseek-pro-x"
    assert routes["coding.simple"].source == "models_by_workload:complex"  # no routine slot: strong fallback
    memory.accept(str(repo), MemoryCandidate("calc.ops.sub keeps integer semantics for every caller",
                                             "PROJECT_CONVENTION", "1" * 32, 0.8, "stability", ("calc/ops.py",)))
    entries = memory.store_factory(str(repo)).project_entries
    assert entries[0] == "The user prefers small, reviewed changes in this project."  # preserved, first
    assert entries[1].startswith("[meu-coding:PROJECT_CONVENTION]")
    service = service_for(tmp_path)
    view = service.start("Add a small function `add` in calc/ops.py and a unit test", str(repo),
                         ("calc/ops.py", "tests/test_ops.py"))
    audit_text = (tmp_path / "audit" / f"{view['task_id']}.json").read_text(encoding="utf-8")
    assert FAKE_KEY not in audit_text and FAKE_KEY not in json.dumps(view)
    assert FAKE_KEY not in caplog.text
