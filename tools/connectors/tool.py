"""Manage independently configured MCP servers and the plugin/skill catalog."""

from typing import Any, Callable, Optional
from tools.connectors.catalog_tool import MANAGE_CATALOG_SCHEMA, manage_catalog
from tools.connectors.config import connectors_available
from tools.connectors.mcp import run_mcp_operation
from tools.connectors.targets import MCP_ACTIONS, normalize_targets
from tools.registry import registry, tool_error


def manage_connections(
    args: dict[str, Any],
    *,
    mcp_backend: Optional[Any] = None,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    connection_callback: Optional[Callable[[dict[str, Any]], Optional[str]]] = None,
) -> str:
    action = str(args.get("action") or "").strip().lower()
    if action not in MCP_ACTIONS:
        return tool_error(
            f"Choose an MCP action: {', '.join(MCP_ACTIONS)}. Hosted accounts are not supported."
        )
    names, error = normalize_targets(args.get("connectors"))
    if error:
        return tool_error(error)
    if not connectors_available():
        return tool_error("MCP connection management is disabled in this profile.")
    return run_mcp_operation(
        names,
        action,
        backend=mcp_backend,
        connection_callback=connection_callback,
        session_id=session_id,
        tool_call_id=tool_call_id,
    )


MANAGE_CONNECTIONS_SCHEMA = {
    "name": "manage_connections",
    "description": (
        "Manage local or independently hosted MCP servers. install adds a bundled catalog entry, "
        "enable re-enables a configured server, authorize runs its OAuth. Pass server names in connectors. "
        "Use this tool instead of hand-editing mcp_servers. Existing approval and authorization flows apply. "
        "When no card is available, show any authorization link to the user; never open it yourself. "
        "Do not repeat skipped or timed-out requests unless the user asks again. Connected tools are "
        "listed in the result and can be used through tool_describe/tool_call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(MCP_ACTIONS)},
            "connectors": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "anyOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "mcp": {"const": True},
                            },
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    ]
                },
            },
        },
        "required": ["action", "connectors"],
        "additionalProperties": False,
    },
}

registry.register(
    name="manage_connections",
    toolset="connections",
    schema=MANAGE_CONNECTIONS_SCHEMA,
    handler=lambda args, **kw: manage_connections(
        args, session_id=kw.get("session_id"), tool_call_id=kw.get("tool_call_id")
    ),
    check_fn=connectors_available,
    emoji="🔗",
)
registry.register(
    name="manage_catalog",
    toolset="catalog",
    schema=MANAGE_CATALOG_SCHEMA,
    handler=lambda args, **kw: manage_catalog(args, session_id=kw.get("session_id")),
    emoji="🧩",
)
