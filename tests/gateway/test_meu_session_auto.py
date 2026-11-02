"""Auto is a durable session choice; neither provider requests nor other chats inherit its selector."""
import json

import pytest

from gateway.session_policy import build_policy, restore_policy
from gateway.session_model_mode import AUTO_MODEL, BASE_MODEL, decorate_options
from hermes_state_local import local_receipt
from tests.gateway.test_session_follow_profile_config import _create, _owner
from tests.gateway.test_session_mutation_model_route import _bind_resolver, _pick


def test_create_freezes_concrete_route_and_separate_auto_policy(tmp_path):
    config = {'model': {'provider': 'deepseek', 'default': BASE_MODEL},
              'smart_model_routing': {'enabled': True}}
    auto = build_policy({'source': 'gui', 'cwd': str(tmp_path), 'provider': 'deepseek',
                         'model': AUTO_MODEL, 'toolsets': []}, config)
    manual = build_policy({'source': 'gui', 'cwd': str(tmp_path), 'provider': 'deepseek',
                           'model': 'deepseek-flash', 'toolsets': []}, config)
    assert auto.model == BASE_MODEL
    assert auto.config()['model']['default'] == BASE_MODEL
    assert auto.config()['smart_model_routing']['enabled'] is True
    assert manual.config()['smart_model_routing']['enabled'] is False
    assert config['smart_model_routing']['enabled'] is True
    payload = decorate_options({'model': BASE_MODEL, 'provider': 'deepseek', 'providers': [
        {'slug': 'deepseek', 'models': [BASE_MODEL, 'deepseek-flash'], 'automatic_routing': True}]}, auto.config())
    assert payload['model'] == AUTO_MODEL and payload['providers'][0]['models'][0] == AUTO_MODEL
    with pytest.raises(Exception, match='invalid_params'):
        build_policy({'source': 'gui', 'cwd': str(tmp_path), 'model': AUTO_MODEL,
                      'provider': 'custom', 'toolsets': []}, config)


@pytest.mark.asyncio
async def test_bot_chat_auto_pick_survives_restore_and_manual_pick_only_changes_that_chat(monkeypatch):
    from gateway import run
    from gateway.session_local import local_session_info
    from gateway.session_contract import SessionRef
    from hermes_cli import model_switch
    from hermes_constants import get_hermes_home
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(run, '_hermes_home', home)
    config = {'model': {'provider': 'deepseek', 'default': BASE_MODEL, 'api_key': 'fixture-only'},
              'smart_model_routing': {'enabled': False}, 'auxiliary': {'title_generation': {'enabled': False}}}
    config_file = home / 'config.yaml'
    config_file.write_text(json.dumps(config), encoding='utf-8')
    seen = []

    def resolve(**kw):
        seen.append(kw['raw_input'])
        return model_switch.ModelSwitchResult(success=True, new_model=kw['raw_input'],
            target_provider='deepseek', base_url='https://api.deepseek.com/v1', api_key='fixture-only')
    monkeypatch.setattr(model_switch, 'switch_model', resolve)
    store, runner, authority, owner = _owner(home)
    _bind_resolver(runner)
    try:
        bot = await _create(owner, authority, home, 'bot')
        other = await _create(owner, authority, home, 'other')
        sid = next(s for s, live in authority.sessions.items() if live is bot)
        other_sid = next(s for s, live in authority.sessions.items() if live is other)
        frames = []
        bot.event_stream.observers.add(frames.append)
        bot.event_stream.execution = {'authority_epoch': authority.epoch, 'execution_generation': 1}
        response = await _pick(owner, authority, sid, {'model': AUTO_MODEL, 'provider': 'deepseek'})
        assert 'result' in response, response
        info_frame = [f['params'] for f in frames if f['params']['type'] == 'session.info'][-1]
        assert info_frame['execution_generation'] == response['result']['execution_generation']
        saved = restore_policy(local_receipt(authority.db, sid)['policy'])
        assert saved.model == BASE_MODEL and saved.config()['smart_model_routing']['enabled'] is True
        assert seen == [BASE_MODEL]
        assert local_session_info(authority, SessionRef(authority.profile_id, sid))['model'] == AUTO_MODEL
        assert local_session_info(authority, SessionRef(authority.profile_id, other_sid))['model'] == BASE_MODEL
        response = await _pick(owner, authority, sid,
            {'model': BASE_MODEL, 'provider': 'deepseek'}, request_id='manual')
        assert 'result' in response, response
        saved = restore_policy(local_receipt(authority.db, sid)['policy'])
        assert saved.model == BASE_MODEL and saved.config()['smart_model_routing']['enabled'] is False
        info_frame = [f['params'] for f in frames if f['params']['type'] == 'session.info'][-1]
        assert info_frame['execution_generation'] == response['result']['execution_generation']
        from ruamel.yaml import YAML
        persisted = YAML(typ='safe').load(config_file.read_text(encoding='utf-8'))
        assert persisted['model'] == config['model']
        assert persisted['smart_model_routing'] == config['smart_model_routing']
        config['smart_model_routing']['enabled'] = True
        config_file.write_text(json.dumps(config), encoding='utf-8')
        response = await _pick(owner, authority, sid, {'model': 'reset'}, request_id='reset-mode')
        assert 'result' in response and response['result'].get('status') != 'noop', response
        saved = restore_policy(local_receipt(authority.db, sid)['policy'])
        assert saved.config()['smart_model_routing']['enabled'] is True
    finally:
        await owner.close()
        store.close_all_db_handles()
