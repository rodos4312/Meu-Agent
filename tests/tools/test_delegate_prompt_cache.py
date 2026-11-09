"""Different helper assignments retain a reusable workspace/rules prefix."""

import os
from pathlib import Path

import pytest

from tools.delegate_tool_progress import _build_child_system_prompt, _COMPLETION_INSTRUCTIONS


@pytest.mark.parametrize('role', ['leaf', 'orchestrator'])
def test_sibling_context_does_not_displace_shared_workspace_rules(tmp_path, role, record_property):
    rules = 'Project convention: preserve unrelated files and report actual checks.\n' * 100
    (tmp_path / 'AGENTS.md').write_text(rules, encoding='utf-8')
    contexts = ['First assignment: inspect inputs; accept exactly one record.',
                'Second assignment: inspect outputs; accept the expected total.']
    prompts = [_build_child_system_prompt('Inspect your assigned deliverable', context,
                workspace_path=str(tmp_path), role=role) for context in contexts]
    shared = os.path.commonprefix(prompts)
    record_property('shared_prefix_bytes', len(shared.encode('utf-8')))
    assert rules.strip() in shared
    assert _COMPLETION_INSTRUCTIONS in shared
    assert str(tmp_path) in shared
    for index, prompt in enumerate(prompts):
        assert contexts[index] in prompt
        assert contexts[1 - index] not in prompt
    assert ('CAN spawn your own subagents' in shared) == (role == 'orchestrator')


def test_coordinator_helpers_send_shared_rules_and_separate_contracts_on_the_wire(tmp_path, monkeypatch, record_property):
    from plugins.delegation.meu_coordinator import MeuCoordinator
    from run_agent import AIAgent
    from tests.e2e.core.history._helpers import NO_BACKGROUND_REVIEW, OFFLINE_CONFIG
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_hermes_home
    from tools.delegate_tool import _build_child_agent

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    rules = 'Shared project rules: preserve unrelated behavior and verify each result.\n' * 100
    (workspace / 'AGENTS.md').write_text(rules, encoding='utf-8')
    monkeypatch.setenv('TERMINAL_CWD', str(workspace))
    home = Path(os.environ['HERMES_HOME'])
    with FakeLLMServer([Text('first report'), Text('second report')]) as server:
        write_hermes_home(home, server.base_url, extra_config=OFFLINE_CONFIG + NO_BACKGROUND_REVIEW)
        parent = AIAgent(provider='custom', model='fake-model', base_url=server.base_url,
                         api_key='fixture-only', enabled_toolsets=['file'], quiet_mode=True,
                         skip_memory=True, skip_context_files=True)
        children = []
        try:
            coordinator = MeuCoordinator(general=True)
            for index, (goal, check) in enumerate([('Inspect input', 'one input record'),
                                                  ('Inspect output', 'one output total')]):
                task = {'goal': goal, 'context': f'Task {index} data', 'acceptance': check,
                        'workload': 'routine', 'parallel_safe': True, 'write_paths': []}
                coordinator.validate_tasks([task], {})
                route = coordinator.route_task(task, {'parent_route': {
                    'provider': 'custom', 'model': 'fake-model', 'base_url': server.base_url}})
                child = _build_child_agent(index, goal, task['context'] + '\n' + route['instructions'],
                    ['file'], route['model'], 3, 2, parent)
                children.append(child)
                assert child.run_conversation(goal, task_id=f'cache-helper-{index}')['final_response']
            requests = server.main_requests()
            assert len(requests) == 2
            system = [request['messages'][0]['content'] for request in requests]
            record_property('shared_system_prefix_bytes', len(os.path.commonprefix(system).encode('utf-8')))
            record_property('shortest_system_bytes', min(len(prompt.encode('utf-8')) for prompt in system))
            assert rules.strip() in os.path.commonprefix(system)
            assert requests[0]['tools'] == requests[1]['tools']
            for index, expected in enumerate(['one input record', 'one output total']):
                assert expected in system[index]
                assert expected not in system[1 - index]
                assert 'Read-only: do not modify project files.' in system[index]
                assert requests[index]['model'] == 'fake-model'
                assert requests[index]['messages'][-1]['role'] == 'user'
                assert ['Inspect input', 'Inspect output'][index] in requests[index]['messages'][-1]['content']
        finally:
            for child in children:
                child.close()
            parent.close()
