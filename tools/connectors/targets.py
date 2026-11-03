"""Validate MCP targets without consulting a hosted account catalog."""

from typing import Any, Optional

MCP_ACTIONS = ("install", "enable", "authorize")


def normalize_targets(raw: Any) -> tuple[list[str], Optional[str]]:
    if isinstance(raw, (str, dict)):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return [], "connectors must contain at least one MCP server name."
    names = []
    for item in raw:
        if isinstance(item, dict):
            if unknown := set(item) - {"name", "mcp"}:
                return (
                    [],
                    f"unknown target field(s): {', '.join(sorted(unknown))}. URLs and credentials belong in the MCP configuration.",
                )
            if item.get("mcp", True) is not True:
                return (
                    [],
                    'Use a server name or {"name": "<server>", "mcp": true}; hosted accounts are not supported.',
                )
            item = item.get("name")
        if not isinstance(item, str) or not item.strip():
            return [], "Every MCP target needs a non-empty name."
        name = item.strip().lower()
        if name not in names:
            names.append(name)
    return names, None
