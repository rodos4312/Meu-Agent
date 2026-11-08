"""General Auto is a durable mode with a concrete provider-bound wire model."""
import copy

import pytest

from gateway.session_model_mode import GENERAL_AUTO_MODEL, apply_selection, decorate_options, display_model
from hermes_state_runtime import RuntimeStoreError


def config():
    return {'model': {'provider': 'openrouter', 'default': 'vendor/pro'}, 'smart_model_routing': {
        'enabled': False, 'provider': 'openrouter', 'routine': 'vendor/lite', 'complex': 'vendor/pro'}}


def test_virtual_selector_never_becomes_a_wire_model():
    value = config()
    assert apply_selection(GENERAL_AUTO_MODEL, 'openrouter', value) == 'vendor/pro'
    assert value['model']['default'] == 'vendor/pro'
    assert display_model('vendor/pro', 'openrouter', value) == GENERAL_AUTO_MODEL
    restored = copy.deepcopy(value)
    payload = decorate_options({'model': 'vendor/pro', 'provider': 'openrouter', 'providers': [
        {'slug': 'openrouter', 'models': ['vendor/lite', 'vendor/pro']},
        {'slug': 'other', 'models': ['other/model']}]}, restored)
    assert payload['model'] == GENERAL_AUTO_MODEL
    assert payload['providers'][0]['models'][0] == GENERAL_AUTO_MODEL
    assert payload['providers'][1]['models'] == ['other/model']
    apply_selection('vendor/lite', 'openrouter', restored)
    assert display_model('vendor/lite', 'openrouter', restored) == 'vendor/lite'
    assert value['smart_model_routing']['enabled'] is True


def test_missing_or_cross_provider_pair_cannot_enable_auto():
    for value, provider in [(config(), 'other'), ({'model': {}}, 'openrouter')]:
        with pytest.raises(RuntimeStoreError):
            apply_selection(GENERAL_AUTO_MODEL, provider, value)


def test_explicit_deepseek_pick_rebinds_a_previous_provider_policy():
    value = config()
    assert apply_selection('deepseek-auto', 'deepseek', value) == 'deepseek-v4-pro'
    assert value['smart_model_routing'] == {
        'enabled': True, 'provider': 'deepseek',
        'routine': 'deepseek-flash', 'complex': 'deepseek-v4-pro'}


@pytest.mark.asyncio
async def test_live_pick_and_restore_keep_auto_out_of_model_resolution(monkeypatch):
    import json
    from gateway import run
    from gateway.session_policy import restore_policy
    from hermes_state_local import local_receipt
    from tests.gateway.test_session_follow_profile_config import _create, _owner
    from tests.gateway.test_session_mutation_model_route import _bind_resolver, _pick
    from hermes_cli import model_switch
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(run, '_hermes_home', home)
    value = config()
    value['model']['api_key'] = 'fixture-only'
    (home / 'config.yaml').write_text(json.dumps(value), encoding='utf-8')
    seen = []

    def resolve(**kw):
        seen.append(kw['raw_input'])
        return model_switch.ModelSwitchResult(success=True, new_model=kw['raw_input'],
               target_provider='openrouter', base_url='https://openrouter.ai/api/v1', api_key='fixture-only')
    monkeypatch.setattr(model_switch, 'switch_model', resolve)
    store, runner, authority, owner = _owner(home)
    _bind_resolver(runner)
    try:
        live = await _create(owner, authority, home, 'auto-openrouter')
        sid = next(s for s, session in authority.sessions.items() if session is live)
        response = await _pick(owner, authority, sid, {'model': GENERAL_AUTO_MODEL, 'provider': 'openrouter'})
        assert 'result' in response, response
        saved = restore_policy(local_receipt(authority.db, sid)['policy'])
        assert saved.model == 'vendor/pro'
        assert seen == ['vendor/pro']
        assert display_model(saved.model, 'openrouter', saved.config()) == GENERAL_AUTO_MODEL
        response = await _pick(owner, authority, sid, {'model': 'vendor/lite', 'provider': 'openrouter'}, request_id='manual')
        assert 'result' in response, response
        saved = restore_policy(local_receipt(authority.db, sid)['policy'])
        assert saved.config()['smart_model_routing']['enabled'] is False
        assert json.loads((home / 'config.yaml').read_text()) == value
    finally:
        await owner.close()
        store.close_all_db_handles()
