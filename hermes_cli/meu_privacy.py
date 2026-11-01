"""Meu's fixed privacy policy; legacy consent cannot enable shared metrics."""

from __future__ import annotations

import copy
from typing import Any


def disable_shared_metrics(config: dict[str, Any]) -> dict[str, Any]:
    """Return an independent config with explicit, persistent opt-outs."""
    result = copy.deepcopy(config)
    telemetry = result.get("telemetry")
    if not isinstance(telemetry, dict):
        telemetry = result["telemetry"] = {}
    shared = telemetry.get("shared_metrics")
    if not isinstance(shared, dict):
        shared = telemetry["shared_metrics"] = {}
    shared.update(enabled=False, send=False, endpoint="", offer_version=2)
    return result


def private_config_changes(changes):
    """Clamp documents and dotted writes, including attempts to unset the opt-out."""
    from dataclasses import replace

    updates = dict(changes.set)
    if changes.document is not None and not updates and not changes.unset:
        return replace(changes, document=disable_shared_metrics(changes.document))
    if "telemetry" in updates:
        updates["telemetry"] = disable_shared_metrics({"telemetry": updates["telemetry"]})["telemetry"]
    if "telemetry.shared_metrics" in updates:
        updates["telemetry.shared_metrics"] = disable_shared_metrics({})["telemetry"]["shared_metrics"]
    for key, value in disable_shared_metrics({})["telemetry"]["shared_metrics"].items():
        updates[f"telemetry.shared_metrics.{key}"] = value
    return replace(
        changes,
        document=disable_shared_metrics(changes.document) if changes.document is not None else None,
        set=updates,
        unset=tuple(key for key in changes.unset if not (
            key in ("telemetry", "telemetry.shared_metrics") or key.startswith("telemetry.shared_metrics."))),
    )
