"""Remove settings belonging to retired Nous services."""

from __future__ import annotations

import copy
from typing import Any

_RETIRED = (("telemetry", "shared_metrics"), ("nous", "keepalive_interval_seconds"))


def strip_retired_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Return a detached document without removed service settings."""
    result = copy.deepcopy(config)
    for section, key in _RETIRED:
        values = result.get(section)
        if isinstance(values, dict):
            values.pop(key, None)
            if not values:
                result.pop(section, None)
    return result


def private_config_changes(changes):
    """Migrate whole documents and dotted writes without touching other settings."""
    from dataclasses import replace

    retired = tuple(f"{section}.{key}" for section, key in _RETIRED)
    updates = {key: value for key, value in changes.set.items()
               if not any(key == path or key.startswith(path + ".") for path in retired)}
    for section, _ in _RETIRED:
        if section in updates:
            updates[section] = strip_retired_settings({section: updates[section]}).get(section, {})
    return replace(
        changes,
        document=strip_retired_settings(changes.document) if changes.document is not None else None,
        set=updates,
        unset=tuple(dict.fromkeys((*changes.unset, *retired))),
    )
