"""Shared real plugin-discovery/delegation fixture for coordinator regressions."""
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import hermes_yaml as yaml


@pytest.fixture
def coordinator(tmp_path, monkeypatch):
    from hermes_cli import plugins as plugins_mod
    from hermes_cli.plugins import PluginManager
    from tools import delegate_tool as dt

    home = tmp_path / "home"
    home.mkdir()
    config = {"delegation": {"backend": "meu_coordinator"}, "smart_model_routing": {"enabled": True}}
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    bundled = tmp_path / "bundled"
    shutil.copytree(Path(__file__).resolve().parents[3] / "plugins" / "delegation", bundled / "delegation",
                    ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MEU_AGENT_MODE", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "meu-test-only")
    monkeypatch.setattr(plugins_mod, "get_bundled_plugins_dir", lambda: bundled)
    manager = PluginManager()
    manager.discover_and_load()
    original_build = dt._build_child_preserving_parent_tools
    original_run = dt._run_single_child
    built = []

    def build(**kwargs):
        built.append(kwargs)
        child = SimpleNamespace(tool_progress_callback=None, model=kwargs["model"],
                                _model_routing_config={"enabled": True})
        return child

    monkeypatch.setattr(dt, "_build_child_preserving_parent_tools", build)
    monkeypatch.setattr(dt, "_run_single_child", lambda task_index, goal, child, **kw: {
        "task_index": task_index, "status": "completed", "summary": "checked", "api_calls": 1, "duration_seconds": 0,
        "route": child._delegate_route})
    parent = SimpleNamespace(session_id="meu-test-parent", provider="deepseek", model="deepseek-v4-pro",
                             base_url="https://api.deepseek.com/v1", api_key="meu-test-only", request_overrides={},
                             tool_progress_callback=None, _delegate_spinner=None, _safe_print=lambda line: None)
    from tools.registry import registry
    parent.tools = [{"type": "function", "function": dt.oneshot_delegate_function(
        registry.get_definitions({"delegate_task"})[0]["function"])}]
    parent._test_original_build = original_build
    parent._test_original_run = original_run
    try:
        yield home, built, parent
    finally:
        manager.unload()
