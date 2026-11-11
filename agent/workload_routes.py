"""Explicit workload routes, shared by the main agent and its Coordinator helpers."""
import re

SLOTS = ("routine", "complex", "web", "vision")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{1,199}")
_WEB = re.compile(r"\b(search (?:the )?(?:web|internet)|browse|look up|lookup|online research|web research|weather|news|"
                  r"αναζητ\w*|ψαξε|βρες.*(?:πηγ|διαδικτυ|ιστοσελ)|καιρο\w*|"
                  r"psakse|anazit\w*)\b", re.IGNORECASE)


def explicit_routes(policy):
    if not isinstance(policy, dict) or not policy.get("routes"):
        return {}
    entries = policy["routes"]
    if not isinstance(entries, dict):
        raise ValueError("Choose a provider and model for each Auto workload.")
    routes = {}
    from hermes_cli.models import normalize_provider
    from hermes_cli.auth import PROVIDER_REGISTRY
    for slot in SLOTS:
        value = entries.get(slot)
        if value in (None, {}):
            continue
        if not isinstance(value, dict):
            raise ValueError(f"Invalid {slot} model route.")
        provider = normalize_provider(str(value.get("provider") or "").strip())
        model = value.get("model")
        if provider not in PROVIDER_REGISTRY or not isinstance(model, str) or not _MODEL.fullmatch(model):
            raise ValueError(f"Choose a known provider and model for {slot}.")
        routes[slot] = {"provider": provider, "model": model}
    return routes


def auto_routes_available(policy, provider):
    if not isinstance(policy, dict) or policy.get("provider") != provider:
        return False
    try:
        routes = explicit_routes(policy)
    except ValueError:
        return False
    return all(slot in routes for slot in ("routine", "complex"))


def choose_workload_route(policy, provider, messages):
    if not isinstance(policy, dict) or policy.get("provider") != provider:
        return None
    routes = explicit_routes(policy)
    if not routes:
        return None
    if not all(slot in routes for slot in ("routine", "complex")):
        raise ValueError("Select both light and complex Auto model routes.")
    from agent.model_routing_policy import complex_work, has_images
    slot = "complex" if complex_work(messages) else "routine"
    from agent.model_routing_policy import user_task_text
    if "web" in routes and _WEB.search(user_task_text(messages)):
        slot = "web"
    chosen = routes[slot]
    if has_images(messages):
        from agent.models_dev import get_model_capabilities
        if "vision" in routes:
            chosen = routes["vision"]
            caps = get_model_capabilities(chosen["provider"], chosen["model"])
            if caps is not None and caps.supports_vision is False:
                raise ValueError("The selected image model does not support images.")
            return chosen
        candidates = [chosen, *[route for route in routes.values() if route != chosen]]
        unknown = []
        for route in candidates:
            caps = get_model_capabilities(route["provider"], route["model"])
            vision = caps.supports_vision if caps else None
            if vision is True:
                return route
            if vision is None:
                unknown.append(route)
        if unknown:
            return unknown[0]
        raise ValueError("The selected Auto models cannot read this image. Select a vision-capable model.")
    return chosen
