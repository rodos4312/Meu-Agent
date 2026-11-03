"""Remove settings belonging to the retired Nous usage collector."""

from __future__ import annotations

import copy
from typing import Any


def strip_retired_metrics(config: dict[str, Any]) -> dict[str, Any]:
    """Return a detached document without the removed collector's settings."""
    result = copy.deepcopy(config)
    telemetry = result.get("telemetry")
    if isinstance(telemetry, dict):
        telemetry.pop("shared_metrics", None)
        if not telemetry:
            result.pop("telemetry", None)
    return result


def private_config_changes(changes):
    """Migrate whole documents and dotted writes without touching other settings."""
    from dataclasses import replace

    retired = "telemetry.shared_metrics"
    updates = {key: value for key, value in changes.set.items()
               if key != retired and not key.startswith(retired + ".")}
    if "telemetry" in updates:
        updates["telemetry"] = strip_retired_metrics({"telemetry": updates["telemetry"]}).get("telemetry", {})
    return replace(
        changes,
        document=strip_retired_metrics(changes.document) if changes.document is not None else None,
        set=updates,
        unset=tuple(dict.fromkeys((*changes.unset, retired))),
    )
