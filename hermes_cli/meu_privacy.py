"""Remove settings belonging to retired Nous services."""

from __future__ import annotations

import copy
from typing import Any

_RETIRED = (
    ("telemetry", "shared_metrics"), ("nous", "keepalive_interval_seconds"),
    ("nous", "anthropic_wire"), ("cron", "chronos"),
)
_RETIRED_CATALOG_URLS = {
    "https://hermes-agent.nousresearch.com/docs/api/model-catalog.json",
    "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/static/api/model-catalog.json",
}


def strip_retired_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Return a detached document without removed service settings."""
    result = copy.deepcopy(config)
    for section, key in _RETIRED:
        values = result.get(section)
        if isinstance(values, dict):
            values.pop(key, None)
            if not values:
                result.pop(section, None)
    catalog = result.get("model_catalog")
    if isinstance(catalog, dict) and catalog.get("url") in _RETIRED_CATALOG_URLS:
        catalog["url"] = ""
    cron = result.get("cron")
    if isinstance(cron, dict) and cron.get("provider") == "chronos":
        cron["provider"] = ""
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
    if "model_catalog" in updates:
        updates["model_catalog"] = strip_retired_settings({"model_catalog": updates["model_catalog"]})["model_catalog"]
    if updates.get("model_catalog.url") in _RETIRED_CATALOG_URLS:
        updates["model_catalog.url"] = ""
    if updates.get("cron.provider") == "chronos":
        updates["cron.provider"] = ""
    return replace(
        changes,
        document=strip_retired_settings(changes.document) if changes.document is not None else None,
        set=updates,
        unset=tuple(dict.fromkeys((*changes.unset, *retired))),
    )
