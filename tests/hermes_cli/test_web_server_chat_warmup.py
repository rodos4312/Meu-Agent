"""Post-ready imports preserve profile context and never own the serving loop."""
import asyncio
from contextvars import ContextVar


def test_warmup_is_deferred_off_loop_with_the_owner_context(monkeypatch):
    from hermes_cli import web_server_chat_warmup as warmup
    profile = ContextVar('test_warmup_profile', default='wrong-profile')
    imported = []
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
    assert all(owner == 'owned-profile' for _, owner in imported)


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
