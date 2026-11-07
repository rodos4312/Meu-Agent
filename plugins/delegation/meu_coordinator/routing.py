"""Select helper models from the active provider's own discovered catalog."""
import re
from typing import Any, Mapping

DEEPSEEK_BACKEND = "meu_coordinator"
GENERAL_BACKEND = "meu_coordinator_general"
COORDINATOR_BACKENDS = {DEEPSEEK_BACKEND, GENERAL_BACKEND}
_DEEPSEEK_FLASH = "deepseek-flash"
_DEEPSEEK_PRO = "deepseek-v4-pro"
_TIER = {"routine": 0, "standard": 1, "complex": 2, "vision": 0}
WORKLOADS = tuple(_TIER)
_LIGHT = {"flash", "luna", "haiku", "mini", "nano", "lite", "spark"}
_HEAVY = {"pro", "astra", "opus", "fable", "ultra", "max"}
_STANDARD = {"sol", "terra", "sonnet"}


def _tier(model: str) -> int | None:
    tokens = set(re.findall(r"[a-z]+", model.rsplit("/", 1)[-1].lower()))
    if tokens & _HEAVY:
        return 2
    if tokens & _LIGHT:
        return 0
    return 1 if tokens & _STANDARD else None


def _endpoint(url: str) -> str:
    return url.rstrip("/").removesuffix("/v1")


def _candidates(provider: str, endpoint: str) -> list[str]:
    from hermes_cli.auth import PROVIDER_REGISTRY
    from hermes_cli.models import cached_provider_model_ids

    # A relay or local runtime can serve a different inventory under the same slug.
    definition = PROVIDER_REGISTRY.get(provider)
    if not definition or not endpoint or _endpoint(endpoint) != _endpoint(definition.inference_base_url):
        return []
    if provider == "deepseek":
        return [_DEEPSEEK_FLASH, _DEEPSEEK_PRO]
    return cached_provider_model_ids(provider, verified_cache_only=True)


def _session_provider(parent_route: Mapping[str, Any]) -> str:
    from agent.delegation_provider import DelegationRouteError
    from hermes_cli.models import normalize_provider

    provider = normalize_provider(parent_route.get("provider") or "")
    requested = str(parent_route.get("requested_provider") or "").strip().lower()
    if provider == "custom" and requested.startswith("custom:"):
        provider = requested
    primary = parent_route.get("primary_provider")
    if primary and normalize_provider(primary) != provider:
        raise DelegationRouteError("The session's selected provider is temporarily unavailable. "
                                   "Resume it before starting Coordinator helpers.")
    return provider


def select_deepseek_model(workload: str, parent_route: Mapping[str, Any]) -> str:
    from agent.delegation_provider import DelegationRouteError

    if _session_provider(parent_route) != "deepseek":
        raise DelegationRouteError("Meu Coordinator · DeepSeek requires a DeepSeek session. "
                                   "Choose Meu Coordinator · General for other providers.")
    return _DEEPSEEK_FLASH if workload in {"routine", "vision"} else _DEEPSEEK_PRO


def select_model(workload: str, parent_route: Mapping[str, Any], overrides: Any = None) -> str:
    from agent.models_dev import get_model_capabilities

    current = str(parent_route.get("model") or "")
    provider = _session_provider(parent_route)
    if workload in {"routine", "standard", "complex"} and isinstance(overrides, Mapping):
        configured = overrides.get(provider)
        # An explicit light/strong pair also owns ordinary implementation;
        # changing the chat model must not introduce a third helper model.
        selected_tier = "complex" if workload == "standard" else workload
        model = configured.get(selected_tier) if isinstance(configured, Mapping) else None
        if isinstance(model, str) and model.strip():
            return model.strip()
    endpoint = str(parent_route.get("base_url") or "")
    models = _candidates(provider, endpoint)
    if not models:
        return current
    tiers = {model: tier for model in models if (tier := _tier(model)) is not None}
    if current:
        tiers.setdefault(current, 1)
    if workload == "vision":
        tiers = {
            model: tier for model, tier in tiers.items()
            if (provider == "deepseek" and model == _DEEPSEEK_FLASH)
            or ((capabilities := get_model_capabilities(provider, model)) is not None
                and capabilities.supports_vision is True)
        }
    target = _TIER[workload]
    return min(tiers, key=lambda model: (abs(tiers[model] - target), model != current), default=current)
