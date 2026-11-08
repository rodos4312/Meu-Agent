"""Auto stays inside the owner's pair/provider and freezes complete tool turns."""
import copy
import json

import httpx
import pytest
from openai import OpenAI

from agent.model_routing_policy import complex_work, selected_pair


def policy():
    return {'enabled': True, 'provider': 'openrouter', 'routine': 'vendor/chosen-lite', 'complex': 'vendor/chosen-pro'}


@pytest.mark.parametrize('text,heavy', [('Καλημέρα', False), ('Φτιάξε εφαρμογή Android', True),
                                         ('Build an APK', True), ('Διόρθωσε τον κώδικα', True),
                                         ('ftiakse mia efarmogi simeioseon', True)])
def test_classification_includes_native_application_requests(text, heavy):
    assert complex_work([{'role': 'user', 'content': text}]) is heavy


def test_pair_never_transfers_to_a_different_provider():
    assert selected_pair(policy(), 'openrouter') == ('vendor/chosen-lite', 'vendor/chosen-pro')
    assert selected_pair(policy(), 'deepseek') is None
    assert selected_pair({**policy(), 'routine': 'bad --provider elsewhere'}, 'openrouter') is None


def test_real_agent_and_sdk_freeze_the_selected_model_through_tools(tmp_path, monkeypatch):
    from hermes_cli.config_backend import write_config_document
    from run_agent import AIAgent
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    write_config_document(tmp_path / 'config.yaml', {'smart_model_routing': policy()})
    current = AIAgent(model='vendor/chosen-pro', provider='openrouter', api_key='fixture-only',
                      base_url='https://openrouter.ai/api/v1', enabled_toolsets=[],
                      quiet_mode=True, skip_memory=True, skip_context_files=True)
    current._current_turn_id = current._inflight_turn_id = 'fixture-turn'
    history = [{'role': 'system', 'content': 'Stable prefix'}, {'role': 'user', 'content': 'Καλημέρα'}]
    original = copy.deepcopy(history)
    tools = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object', 'properties': {}}}}]
    seen = []

    def handle(request):
        body = json.loads(request.content)
        assert request.url.host == 'openrouter.ai'
        seen.append(body['model'])
        assert body['model'] == 'vendor/chosen-lite'
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0,
                              'model': body['model'], 'choices': [{'index': 0, 'finish_reason': 'stop',
                              'message': {'role': 'assistant', 'content': 'Done'}}]})
    try:
        with OpenAI(api_key='fixture-only', base_url='https://openrouter.ai/api/v1',
                    http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
            client.chat.completions.create(**current._build_api_kwargs(history, tools))
            assert history == original
            history.append({'role': 'user', 'content': 'Internal budget: implement a complex algorithm'})
            client.chat.completions.create(**current._build_api_kwargs(history, tools))
        assert seen == ['vendor/chosen-lite', 'vendor/chosen-lite']
        assert current.model == 'vendor/chosen-pro'
    finally:
        current.close()
