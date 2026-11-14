"""Reuse the serve owner's idle time for imports, never for an agent or inference."""
import asyncio
import importlib
import logging

logger = logging.getLogger(__name__)


def _import_chat_modules():
    for module in ('run_agent', 'tui_gateway.agent_factory', 'agent.workload_turn_route'):
        try:
            importlib.import_module(module)
        except Exception:  # health: allow BLE001 -- speculative import; the actual request reports errors
            logger.debug("Chat import warm-up unavailable for %s", module, exc_info=True)


def schedule_chat_import_warmup(*, delay=2.0):
    """Arm after the socket is ready; to_thread carries the owner's profile context."""
    async def warm():
        await asyncio.sleep(delay)
        await asyncio.to_thread(_import_chat_modules)
    return asyncio.get_running_loop().create_task(warm(), name='chat-import-warmup')
