"""Shared-metrics transmission is unavailable in Meu, regardless of old configuration."""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ENDPOINT = ""


@dataclass(frozen=True)
class SendConfig:
    enabled: bool
    send: bool
    endpoint: str


def resolve_send_config(config: dict | None) -> SendConfig:
    """No config, environment value or legacy consent can enable uploads."""
    return SendConfig(enabled=False, send=False, endpoint="")
