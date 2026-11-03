"""Lazy public boundary for MCP and plugin/skill connection operations."""
import importlib
_LAZY_EXPORTS = {
    "MANAGE_CONNECTIONS_SCHEMA": "tools.connectors.tool",
    "connectors_available": "tools.connectors.config",
    "manage_connections": "tools.connectors.tool",
}
__all__ = sorted(_LAZY_EXPORTS)

def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value

def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
