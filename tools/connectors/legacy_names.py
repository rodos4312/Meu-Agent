"""Read old connector names when displaying saved conversations. No transport or credentials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

__all__ = [
    "CONNECTOR_NAME_PREFIX",
    "ConnectorName",
    "is_connector_name",
    "parse_connector_name",
]

CONNECTOR_NAME_PREFIX = "connectors__"


@dataclass(frozen=True)
class ConnectorName:
    raw: str
    connector: str
    tool: str


def is_connector_name(name: object) -> bool:
    """Prefix match only; malformed names are rejected by the parser."""
    return isinstance(name, str) and name.startswith(CONNECTOR_NAME_PREFIX)


def parse_connector_name(name: object) -> Optional[ConnectorName]:
    """Use a bounded split so tool slugs retain internal underscores."""
    if not isinstance(name, str):
        return None
    parts = name.split("__", 2)
    if len(parts) != 3:
        return None
    prefix, connector, tool = parts
    if prefix != "connectors" or not connector or not tool:
        return None
    return ConnectorName(raw=name, connector=connector, tool=tool)
