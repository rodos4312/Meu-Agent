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


def _explicit_model(workload: str, provider: str, overrides: Any) -> str | None:
    from agent.models_dev import get_model_capabilities
    from agent.delegation_provider import DelegationRouteError

    configured = overrides.get(provider) if isinstance(overrides, Mapping) else None
    if not isinstance(configured, Mapping):
        return None
    # The strong choice also owns ordinary implementation, even after a manual
    # chat-model change. A visual task must not escape an explicit pair either.
    tier = "complex" if workload == "standard" else workload
    chosen = configured.get(tier)
    if isinstance(chosen, str) and chosen.strip():
        return chosen.strip()
    if workload != "vision":
        return None
    pair = [configured.get(name) for name in ("routine", "complex")]
    if not all(isinstance(model, str) and model.strip() for model in pair):
        return None
    candidates = []
    for model in pair:
        model = model.strip()
        capabilities = get_model_capabilities(provider, model)
        vision = capabilities.supports_vision if capabilities is not None else None
        if vision is True:
            return model
        candidates.append((model, vision))
    # Unknown metadata is not proof of incompatibility. Prefer the selected
    # strong model in that case; the actual provider still decides support.
    for model, vision in reversed(candidates):
        if vision is None:
            return model
    raise DelegationRouteError("Neither selected Coordinator model supports vision. "
                               "Choose a vision-capable model within the active provider.")


def select_model(workload: str, parent_route: Mapping[str, Any], overrides: Any = None) -> str:
    from agent.models_dev import get_model_capabilities

    current = str(parent_route.get("model") or "")
    provider = _session_provider(parent_route)
    explicit = _explicit_model(workload, provider, overrides)
    if explicit:
        return explicit
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
