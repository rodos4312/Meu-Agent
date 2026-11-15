"""Post-ready imports preserve profile context and never own the serving loop."""
import asyncio
from contextvars import ContextVar
import threading


def test_warmup_is_deferred_off_loop_with_the_owner_context(monkeypatch):
    from hermes_cli import web_server_chat_warmup as warmup
    profile = ContextVar('test_warmup_profile', default='wrong-profile')
    imported = []
    from agent import process_bootstrap
    owner_thread = threading.get_ident()
    sdk_calls = []
    monkeypatch.setattr(process_bootstrap, '_load_openai_cls',
                        lambda: (sdk_calls.append((profile.get(), threading.get_ident())),
                                 imported.append(('sdk-class', profile.get()))))
    monkeypatch.setattr(warmup.importlib, 'import_module', lambda name: imported.append((name, profile.get())))

    async def scenario():
        token = profile.set('owned-profile')
        try:
            task = warmup.schedule_chat_import_warmup(delay=0)
            assert imported == []  # scheduling cannot do synchronous cold imports
            await task
        finally:
            profile.reset(token)
    asyncio.run(scenario())
    assert ('run_agent', 'owned-profile') in imported
    assert ('openai', 'owned-profile') in imported
    assert ('gateway.run', 'owned-profile') in imported
    assert all(owner == 'owned-profile' for _, owner in imported)
    assert imported[0] == ('sdk-class', 'owned-profile')
    assert len(sdk_calls) == 1
    assert sdk_calls[0][0] == 'owned-profile'
    assert sdk_calls[0][1] != owner_thread


def test_speculative_import_failure_does_not_break_serving(monkeypatch):
    from hermes_cli import web_server_chat_warmup as warmup
    imported = []
    def importing(name):
        imported.append(name)
        if name == 'run_agent':
            raise ImportError('optional dependency unavailable')
    monkeypatch.setattr(warmup.importlib, 'import_module', importing)
    async def scenario():
        await warmup.schedule_chat_import_warmup(delay=0)
    asyncio.run(scenario())
    assert 'tui_gateway.agent_factory' in imported


def test_lazy_sdk_failure_is_best_effort(monkeypatch):
    from agent import process_bootstrap
    from hermes_cli import web_server_chat_warmup as warmup
    monkeypatch.setattr(warmup.importlib, 'import_module', lambda name: None)
    def unavailable():
        raise ImportError('SDK not installed in this profile')
    monkeypatch.setattr(process_bootstrap, '_load_openai_cls', unavailable)
    async def scenario():
        await warmup.schedule_chat_import_warmup(delay=0)
    asyncio.run(scenario())
