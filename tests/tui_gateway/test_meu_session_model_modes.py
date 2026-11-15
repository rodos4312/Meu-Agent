"""Explicit picks must survive the legacy Android gateway's Auto default and resume."""
import copy
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def build(monkeypatch, tmp_path):
    import model_tools  # real provider registration
    from tui_gateway import server
    from agent.agent_init_request_policy import init_model_routing_policy

    config = {"model": {"provider": "deepseek", "default": "deepseek-v4-pro"},
              "smart_model_routing": {"enabled": True, "provider": "deepseek",
                  "base_model": "deepseek-v4-pro", "routine": "deepseek-flash", "complex": "deepseek-v4-pro",
                  "routes": {"routine": {"provider": "deepseek", "model": "deepseek-flash"},
                             "complex": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                             "web": {"provider": "gemini", "model": "gemini-3.8-flash"}}}}
    monkeypatch.setattr(server, "_load_cfg", lambda: copy.deepcopy(config))
    monkeypatch.setattr(server, "_startup_system_prompt", lambda *a: "frozen test prefix")
    monkeypatch.setattr(server, "_load_enabled_toolsets", lambda *a: [])
    monkeypatch.setattr(server, "_load_disabled_toolsets", list)
    monkeypatch.setattr(server, "_agent_cbs", lambda *a: {})
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_sessions", {})
    monkeypatch.setattr(server, "_load_provider_routing", dict)
    monkeypatch.setattr(server, "_load_reasoning_config", lambda *a: None)
    monkeypatch.setattr(server, "_load_fallback_model", lambda: None)

    def runtime(pick, provider):
        return ((pick or {}).get("model", "deepseek-v4-pro"),
                {"provider": (pick or {}).get("provider") or "deepseek", "base_url": "https://api.deepseek.com/v1"})
    monkeypatch.setattr(server, "_resolve_agent_model_runtime", runtime)

    def construct(**kwargs):
        agent = SimpleNamespace(**kwargs)
        init_model_routing_policy(agent, copy.deepcopy(config))
        agent._prepare_messages_for_non_vision_model = lambda messages, **kw: messages
        return agent
    monkeypatch.setattr("run_agent.AIAgent", construct)

    def make(pick, **kwargs):
        return server._make_agent("owned-mode-test", "owned-mode-test", model_override=pick,
                                  session_id="owned-mode-test", context_cwd_is_launch_artifact=False,
                                  cwd_override=str(tmp_path), **kwargs)
    return server, config, make


@pytest.mark.parametrize("model,text", [
    ("deepseek-v4-pro", "Καλημέρα"),
    ("deepseek-flash", "Analyze this complex architecture and prove correctness"),
])
def test_explicit_model_is_not_overridden_by_auto(build, model, text, caplog):
    from tui_gateway.methods_session_model_guard import create_overrides
    from agent.request_routing import prepare_routed_request
    from providers import get_provider_profile
    _, _, make = build
    pick, _, _ = create_overrides({"provider": "deepseek", "model": model})
    agent = make(pick)
    assert agent._model_routing_config.get("enabled") is False
    with caplog.at_level('INFO', logger='agent.request_routing'):
        chosen, _ = prepare_routed_request(agent, get_provider_profile("deepseek"), [{"role": "user", "content": text}])
    assert chosen == model
    assert f'Selected request route: provider=deepseek model={model}' in caplog.text
    assert text not in caplog.text


def test_auto_pick_resolves_virtual_id_and_survives_persisted_resume(build):
    from tui_gateway.methods_session_model_guard import create_overrides
    server, _, make = build
    pick, _, _ = create_overrides({"provider": "deepseek", "model": "meu-auto"})
    agent = make(pick)
    assert agent.model == "deepseek-v4-pro"
    assert agent._model_routing_config["enabled"] is True
    agent.api_mode = "chat_completions"
    agent.service_tier = None
    persisted = server._runtime_model_config(agent)
    assert persisted["smart_model_routing"]["enabled"] is True
    resumed = server._stored_session_runtime_overrides({"model": agent.model, "model_config": persisted})
    restored = make(resumed["model_override"])
    assert restored._model_routing_config == agent._model_routing_config
    assert "api_key" not in persisted["smart_model_routing"]


def test_manual_mode_survives_resume_without_changing_the_profile(build):
    from tui_gateway.methods_session_model_guard import create_overrides
    server, config, make = build
    before = copy.deepcopy(config)
    pick, _, _ = create_overrides({"provider": "deepseek", "model": "deepseek-flash"})
    agent = make(pick)
    agent.api_mode = "chat_completions"
    agent.service_tier = None
    persisted = server._runtime_model_config(agent)
    resumed = server._stored_session_runtime_overrides({"model": agent.model, "model_config": persisted})
    assert make(resumed["model_override"])._model_routing_config.get("enabled") is False
    assert config == before


@pytest.mark.parametrize("text", [
    "Διάβασε τη σελίδα https://example.com και πες μου τον τίτλο",
    "Άνοιξε την ιστοσελίδα example.com και βρες την ημερομηνία",
    "Ψάξε στο διαδίκτυο πηγές για αυτή την πληροφορία",
])
def test_greek_web_read_requests_use_configured_web_role(build, text):
    from agent.workload_routes import choose_workload_route
    _, config, _ = build
    assert choose_workload_route(config["smart_model_routing"], "deepseek", [{"role": "user", "content": text}]) == {
        "provider": "gemini", "model": "gemini-3.8-flash"}


def test_live_manual_auto_reset_and_once_preserve_mode(build, monkeypatch):
    from hermes_cli import config as cli_config, model_switch
    server, config, make = build
    medium = {'enabled': True, 'effort': 'medium'}
    agent = make(None, reasoning_config_override=medium)
    agent.api_key = 'test-only'
    agent.api_mode = 'chat_completions'
    agent.service_tier = None
    agent.switch_model = lambda **kw: (
        setattr(agent, 'model', kw['new_model']), setattr(agent, 'provider', kw['new_provider']),
        setattr(agent, 'reasoning_config', None))
    session = {'agent': agent, 'session_key': 'owned-mode-test'}
    monkeypatch.setattr(cli_config, 'load_config', lambda: copy.deepcopy(config))
    monkeypatch.setattr(model_switch, 'switch_model', lambda **kw: SimpleNamespace(
        success=True, new_model=kw['raw_input'], target_provider='deepseek',
        api_key='test-only', base_url='https://api.deepseek.com/v1', api_mode='chat_completions',
        warning_message='', usage_notice=''))
    monkeypatch.setattr(server, '_merge_preflight_warning', lambda *a: None)
    monkeypatch.setattr(server, '_restart_slash_worker', lambda *a: None)
    monkeypatch.setattr(server, '_persist_live_session_system_prompt', lambda *a: None)
    monkeypatch.setattr(server, '_append_model_switch_marker', lambda *a, **kw: None)
    monkeypatch.setattr(server, '_emit_session_info', lambda *a: None)
    saved = []
    monkeypatch.setattr(server, '_persist_live_session_runtime', lambda *a: saved.append(copy.deepcopy(agent._model_routing_config)))
    switch = lambda model: server._apply_model_switch('owned-mode-test', session,
        model + ' --provider deepseek', confirm_expensive_model=True, persist_override=False)
    switch('deepseek-v4-pro')
    assert agent.reasoning_config == medium
    assert saved[-1]['enabled'] is False
    assert session['model_override']['smart_model_routing']['enabled'] is False
    # Reset must restore Auto even when the physical primary model is unchanged.
    server._reset_session_model_override('owned-mode-test', session)
    assert agent._model_routing_config['enabled'] is True
    assert switch('meu-auto')['value'] == 'meu-auto'
    assert agent.model == 'deepseek-v4-pro'
    assert saved[-1]['enabled'] is True
    server._apply_model_switch('owned-mode-test', session, 'deepseek-flash --provider deepseek --once',
                              confirm_expensive_model=True, persist_override=False)
    assert agent._model_routing_config['enabled'] is False
    server._restore_agent_model_runtime(agent, session['one_turn_model_restore'])
    assert agent._model_routing_config['enabled'] is True
    assert agent.reasoning_config == medium
    assert agent._session_reasoning_override == medium


@pytest.mark.parametrize('text', ['Γράψε μια σελίδα κειμένου για ένα βιβλίο', 'Implement a web search function in this code'])
def test_writing_a_page_or_search_function_is_not_a_web_lookup(build, text):
    from agent.workload_routes import choose_workload_route
    _, config, _ = build
    route = choose_workload_route(config['smart_model_routing'], 'deepseek', [{'role': 'user', 'content': text}])
    assert route['provider'] == 'deepseek'


def test_manual_chat_still_advertises_its_configured_auto_roles(build, monkeypatch):
    from tui_gateway.methods_session_model_guard import create_overrides
    server, _config, make = build
    pick, _, _ = create_overrides({'provider': 'deepseek', 'model': 'deepseek-flash'})
    agent = make(pick)
    monkeypatch.setattr(server, '_session_agent', lambda params: agent)
    monkeypatch.setattr(server, '_model_skew_err', lambda rid: None)
    monkeypatch.setattr(server, '_model_picker_context', lambda current: None)
    monkeypatch.setattr('hermes_cli.inventory.build_model_options_payload', lambda *a, **kw: {
        'model': 'deepseek-flash', 'provider': 'deepseek',
        'providers': [{'slug': 'deepseek', 'automatic_routing': True, 'models': ['deepseek-flash', 'deepseek-v4-pro']}]})
    payload = server._methods['model.options'](1, {})['result']
    assert payload['model'] == 'deepseek-flash'
    assert payload['providers'][0]['models'][0] == 'meu-auto'
    assert agent._model_routing_config['enabled'] is False


def test_new_auto_chat_preserves_medium_reasoning_on_persisted_resume(build):
    from tui_gateway.methods_session_model_guard import create_overrides
    server, _, make = build
    pick, reasoning, _ = create_overrides({"provider": "deepseek", "model": "meu-auto",
                                          "reasoning_effort": "medium"})
    agent = make(pick, reasoning_config_override=reasoning)
    assert agent._session_reasoning_override == {"enabled": True, "effort": "medium"}
    agent.api_mode = "chat_completions"
    agent.service_tier = None
    saved = server._runtime_model_config(agent)
    restored = server._stored_session_runtime_overrides({"model": agent.model, "model_config": saved})
    resumed = make(restored.get("model_override"), reasoning_config_override=restored["reasoning_config_override"])
    assert resumed._session_reasoning_override == agent._session_reasoning_override


@pytest.mark.parametrize("scope", ["session", "global"])
def test_reasoning_pick_marks_only_session_scoped_pins(build, monkeypatch, scope):
    from tui_gateway.methods_session_model_guard import create_overrides
    server, _, make = build
    pick, _, _ = create_overrides({"provider": "deepseek", "model": "meu-auto"})
    agent = make(pick)
    session = {"agent": agent, "session_key": "owned-mode-test"}
    monkeypatch.setattr(server, "_persist_live_session_runtime", lambda *a: None)
    monkeypatch.setattr(server, "_emit_session_info", lambda *a: None)
    writes = []
    monkeypatch.setattr(server, "_write_config_key", lambda *a: writes.append(a))
    server._set_reasoning("owned", {"session_id": "owned-mode-test", "scope": scope},
                          "reasoning", "medium", session)
    assert agent.reasoning_config == {"enabled": True, "effort": "medium"}
    assert agent._session_reasoning_override == (agent.reasoning_config if scope == "session" else None)
    assert bool(writes) is (scope == "global")


@pytest.mark.parametrize("selection,enabled,physical", [
    ("meu-auto", True, "deepseek-v4-pro"),
    ("deepseek-flash", False, "deepseek-flash"),
    (None, True, "deepseek-v4-pro"),
])
def test_first_durable_row_restores_mode_before_any_model_switch(build, tmp_path, selection, enabled, physical):
    from hermes_state import SessionDB
    from tui_gateway.methods_session_model_guard import create_overrides
    server, _, make = build
    params = {"provider": "deepseek", "model": selection} if selection else {}
    pick, _, _ = create_overrides(params)
    model, config = server._workdir_row_model_config({"session_key": "owned-first-row", "model_override": pick})
    with SessionDB(db_path=tmp_path / "first-row.db") as db:
        db.create_session("owned-first-row", source="desktop", model=model, model_config=config)
        row = db.get_session("owned-first-row")
    assert row["model"] == physical
    saved = json.loads(row["model_config"])
    assert saved["smart_model_routing"]["enabled"] is enabled
    restored = server._stored_session_runtime_overrides(row)
    agent = make(restored.get("model_override"))
    assert agent._model_routing_config["enabled"] is enabled
