"""Reject retired service configuration; never migrate or reuse old accounts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from hermes_cli.config_backend import ConfigBackendUnavailable, ConfigValueError

_RETIRED_PATHS = (
    "nous", "providers.nous", "providers.solstice", "telemetry.shared_metrics",
    "cron.chronos", "display.credits_notices", "dashboard.oauth",
    *(f"{section}.use_gateway" for section in ("browser", "web", "image_gen", "video_gen", "tts", "stt")),
)
_RETIRED_NAMES = frozenset({"nous", "solstice", "retired-managed"})
_MESSAGE = (
    "Retired Nous settings are not supported. Remove the obsolete settings and configure "
    "an independent provider. No automatic migration was performed."
)

def is_retired_service_url(value: object) -> bool:
    """Identify retired service hosts and the former catalog mirror, never other providers."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    retired_hosts = ("nousresearch.com", "staging-nousresearch.com")
    if any(host == root or host.endswith("." + root) for root in retired_hosts):
        return True
    return (host == "raw.githubusercontent.com" and parsed.path.rstrip("/").lower()
            == "/nousresearch/hermes-agent/main/website/static/api/model-catalog.json")


def require_independent_endpoint(value: object) -> None:
    """Reject a retired endpoint before routing or constructing any HTTP transport."""
    if is_retired_service_url(value):
        from hermes_cli.auth import AuthError
        raise AuthError("Retired Nous service endpoints are not supported. Configure an independent provider.",
                        code="retired_service")


def _contains_retired_setting(value: Any, path: str = "") -> bool:
    if any(path == retired or path.startswith(retired + ".") for retired in _RETIRED_PATHS):
        return True
    key = path.rsplit(".", 1)[-1]
    if isinstance(value, str):
        name = value.strip().lower()
        if key in {"provider", "backend", "cloud_provider", "search_backend", "extract_backend"}:
            if name in _RETIRED_NAMES or (path == "cron.provider" and name == "chronos"):
                return True
        if path == "terminal.modal_mode" and name == "managed":
            return True
        if path.startswith("custom_providers.") and key in {"name", "id"} and name in _RETIRED_NAMES:
            return True
        return key in {"url", "base_url", "endpoint"} and is_retired_service_url(value)
    if isinstance(value, Mapping):
        return any(_contains_retired_setting(child, f"{path}.{key}" if path else str(key))
                   for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_retired_setting(child, f"{path}.{index}") for index, child in enumerate(value))
    return False


def validate_independent_config(config: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on obsolete settings, without editing, converting or copying the document."""
    if _contains_retired_setting(config):
        # SystemExit is deliberate: generic config callers must not swallow this and serve defaults.
        raise ConfigBackendUnavailable(_MESSAGE)
    return config


def validate_independent_changes(changes) -> None:
    """Refuse unsupported whole or dotted writes before any backend mutation; explicit unsets remain valid."""
    if ((changes.document is not None and _contains_retired_setting(changes.document))
            or _contains_retired_setting(changes.set)):
        raise ConfigValueError(_MESSAGE)
