"""Reuse the serve owner's idle time for imports, never for an agent or inference."""
import asyncio
import importlib
import logging
import time

logger = logging.getLogger(__name__)


def _import_chat_modules():
    started = time.monotonic()
    for module in ('openai', 'run_agent', 'tui_gateway.agent_factory',
                   'agent.workload_turn_route', 'gateway.run'):
        try:
            importlib.import_module(module)
        except Exception:  # health: allow BLE001 -- speculative import; the actual request reports errors
            logger.debug("Chat import warm-up unavailable for %s", module, exc_info=True)

    try:
        # Importing the openai module leaves the agent's class proxy cold.
        # Resolve through its existing cache, without constructing a client.
        from agent.process_bootstrap import _load_openai_cls
        _load_openai_cls()
    except Exception:  # health: allow BLE001 -- optional warm-up; actual request reports errors
        logger.debug("Chat SDK class warm-up unavailable", exc_info=True)
    logger.info("Chat imports ready in %.2fs", time.monotonic() - started)


def schedule_chat_import_warmup(*, delay=2.0):
    """Arm after the socket is ready; to_thread carries the owner's profile context."""
    async def warm():
        await asyncio.sleep(delay)
        await asyncio.to_thread(_import_chat_modules)
    return asyncio.get_running_loop().create_task(warm(), name='chat-import-warmup')
