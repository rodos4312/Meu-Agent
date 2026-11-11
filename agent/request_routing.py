"""Resolve an explicit provider routing policy without mutating agent or prompt state."""

import contextlib
import logging

logger = logging.getLogger(__name__)


def prepare_routed_request(agent, profile, messages):
    model = agent.model
    policy = getattr(agent, "_model_routing_config", {})
    if (not getattr(agent, "_workload_route_state", None)
            and profile is not None and isinstance(policy, dict) and policy.get("enabled") is True
            and (not policy.get("provider") or policy["provider"] == agent.provider)):
        from agent.model_routing_policy import choose_from_pair
        selected = choose_from_pair(policy, agent.provider, messages) if agent.provider != "deepseek" else None
        model = selected if selected is not None else profile.resolve_request_model(model, messages=messages, policy=policy)
        turn = getattr(agent, "_current_turn_id", None) if getattr(agent, "_inflight_turn_id", None) else None
        key = (turn, agent.provider, agent.model)
        previous = getattr(agent, "_turn_model_route", None)
        has_images = any(isinstance(p, dict) and p.get("type") in {"image_url", "image", "input_image"}
                         for m in messages if isinstance(m, dict) and isinstance(m.get("content"), list)
                         for p in m["content"])
        # Synthetic continuation/budget messages must not downgrade a running task.
        # A newly introduced image is the exception: keep the request compatible.
        if turn and previous and previous[0] == key and not has_images:
            model = previous[1]
        if turn:
            agent._turn_model_route = (key, model)
    if model != agent.model:
        prepared = agent._prepare_messages_for_non_vision_model(messages, model=model)
    else:
        prepared = agent._prepare_messages_for_non_vision_model(messages)
    # No prompt text or credentials are written into the routing log.
    if getattr(agent, "_last_request_route", None) != model:
        if isinstance(policy, dict) and policy.get("enabled") is True:
            logger.info("Automatic request route: provider=%s model=%s", agent.provider, model)
        agent._last_request_route = model
    agent._request_route_identity = (agent.provider, agent.model, model)
    return model, prepared


def active_request_model(agent):
    """The routed request's model for local accounting; ignore stale routes after a switch."""
    route = getattr(agent, "_request_route_identity", None)
    if (getattr(agent, "api_mode", None) == "chat_completions" and isinstance(route, tuple)
            and len(route) == 3 and route[:2] == (agent.provider, agent.model)):
        return route[2]
    return agent.model


def request_temperature(agent):
    # _fixed_temperature_for_model may return the OMIT_TEMPERATURE sentinel
    # (temperature omitted entirely), a numeric override, or None.
    _omit_temp, _fixed_temp = False, None
    with contextlib.suppress(Exception):
        from agent.auxiliary_client import _fixed_temperature_for_model, OMIT_TEMPERATURE
        _ft = _fixed_temperature_for_model(agent.model, agent.base_url)
        _omit_temp = _ft is OMIT_TEMPERATURE
        _fixed_temp = None if _omit_temp else _ft

    return _omit_temp, _fixed_temp
