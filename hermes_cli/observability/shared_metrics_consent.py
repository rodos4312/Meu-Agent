"""Meu's permanent opt-out, shared by terminal, Desktop and dashboard callers."""
from __future__ import annotations

from typing import Any

OFFER_VERSION = 2
OFFER_CHOICES = (("Usage statistics disabled in Meu", False, False),)


def consent_state(raw_cfg: Any) -> dict:
    """Never prompt or honor an old opt-in."""
    return {"enabled": False, "send": False, "decided": True, "reask": False}


def set_answer(target: dict, enabled: bool, send: bool) -> None:
    """Write one answer into a config mapping: both opt-ins plus the offer version that settles it."""
    telemetry = target.get("telemetry")
    if not isinstance(telemetry, dict):
        telemetry = target["telemetry"] = {}
    section = telemetry.get("shared_metrics")
    if not isinstance(section, dict):
        section = telemetry["shared_metrics"] = {}
    section["enabled"], section["send"] = False, False
    section["endpoint"] = ""
    section["offer_version"] = OFFER_VERSION


def save_consent(enabled: bool, send: bool, config: dict | None = None) -> None:
    """Write both keys into the user's raw config.yaml now. ``save_config`` strips values equal
    to the shipped defaults, so a "No thanks" (both false) saved through it vanished and the
    profile was asked again on every surface. ``config`` (a caller's in-memory copy, e.g. the
    wizard's) gets the same answer so its later save agrees. Sending cannot outlive collection."""
    from hermes_cli.config import (
        _write_user_config, get_config_path, is_managed, managed_error, require_readable_config_before_write,
    )
    from hermes_cli.setup import _record_send_consent_change

    if is_managed():
        managed_error("save configuration")
        return
    enabled = send = False
    config_path = get_config_path()
    user_config = require_readable_config_before_write(config_path)
    set_answer(user_config, enabled, send)
    _write_user_config(config_path, user_config)
    if config is not None:
        set_answer(config, enabled, send)
    # Unconditional: a send key already false may still have an open consent window.
    _record_send_consent_change(enabled=send)
    if not enabled:
        from hermes_constants import get_hermes_home

        from .shared_metrics_process import purge_pending_receipts

        purge_pending_receipts(get_hermes_home())


def offer_consent(config: dict | None = None, *, reask: bool = False) -> bool:
    """Keep compatibility for older callers without offering an opt-in."""
    save_consent(False, False, config)
    return True


def offer_consent_if_undecided(config: dict | None = None) -> None:
    """Meu never asks for telemetry consent."""


def offer_consent_before_chat(args: Any) -> None:
    """Keep startup compatible without prompting or changing the conversation."""
