"""Queued delegates are readable before their first model request."""

from hermes_state import SessionDB
from tests.tools.test_delegate import _make_mock_parent
from tools.delegate_tool import _build_child_agent


def test_queued_child_is_recorded_and_first_turn_keeps_runtime_metadata(tmp_path, monkeypatch):
    parent = _make_mock_parent()
    parent.session_id = "coordinator"
    parent.prefill_messages = None
    parent.enabled_toolsets = ["file"]
    parent.disabled_toolsets = []
    parent_db = SessionDB(db_path=tmp_path / "state.db")
    parent._session_db = parent_db
    child = None
    try:
        parent_db.create_session(parent.session_id, "cli", session_key="parent-transport")
        monkeypatch.setattr("tools.delegate_tool._load_config", dict)
        monkeypatch.setattr("tools.delegate_tool._resolve_child_credential_pool", lambda *_a, **_kw: None)
        monkeypatch.setattr("tools.delegate_tool._resolve_child_runtime", lambda *_a, **_kw: {
            "model": "gpt-4o-mini",
            "provider": "custom",
            "api_mode": "chat_completions",
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": "test",
        })
        child = _build_child_agent(
            task_index=0, goal="Inspect the change", context=None, toolsets=["file"],
            model="gpt-4o-mini", max_iterations=5, task_count=1, parent_agent=parent,
        )
        sid = child.session_id
        queued = parent_db.get_session(sid)
        assert queued is not None
        assert queued["source"] == "subagent"
        assert queued["parent_session_id"] == parent.session_id
        assert queued["session_key"] is None
        assert queued["system_prompt"] is None
        assert parent_db.get_session_model_config_value(sid, "_delegate_from") == parent.session_id
        assert parent_db.get_messages(sid) == []

        # A pre-turn writer can add data before the constructor's usual persistence.
        parent_db.patch_session_model_config(sid, {"_queued_probe": 1})
        child._cached_system_prompt = "Child first-turn prompt"
        child._ensure_db_session()
        started = parent_db.get_session(sid)
        assert started["model"] == "gpt-4o-mini"
        assert started["system_prompt"] == "Child first-turn prompt"
        assert parent_db.get_session_model_config_value(sid, "max_iterations") == 5
        assert parent_db.get_session_model_config_value(sid, "_queued_probe") == 1

        child.close()
        child = None
        assert parent_db.get_session(sid)["ended_at"] is not None
    finally:
        if child is not None:
            child.close()
        parent_db.close()
