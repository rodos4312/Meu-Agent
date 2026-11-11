"""Apply a user-configured workload route for one turn, then restore the session."""
import logging

logger = logging.getLogger(__name__)


def begin_workload_turn_route(agent, messages, system_prompt):
    policy = getattr(agent, "_model_routing_config", {})
    if not isinstance(policy, dict) or policy.get("enabled") is not True or not policy.get("routes"):
        return system_prompt
    if getattr(agent, "_voice_turn_pending", False):
        return system_prompt
    from agent.workload_routes import choose_workload_route, explicit_routes
    target = choose_workload_route(policy, agent.provider, messages)
    if target is None:
        return system_prompt
    from agent.voice_turn_route import _capture
    from agent.route_binding import bind_route_entry
    state = _capture(agent)
    import copy
    state["reasoning_config"] = copy.deepcopy(getattr(agent, "reasoning_config", None))
    state["fallback_chain"] = getattr(agent, "_fallback_chain", [])
    agent._workload_route_state = state
    # Only the explicitly chosen route can service this workload.
    agent._fallback_chain = []
    if bind_route_entry(agent, target, target["provider"], target["model"]) is None:
        raise ValueError(f"Configure the API key for {target['provider']} before using Auto.")
    vision = explicit_routes(policy).get("vision")
    if vision:
        from agent.auxiliary_task_config import _SESSION_AUXILIARY, _AUX_ROUTE_KEYS, session_auxiliary_scope
        from hermes_cli.config import load_config_readonly
        auxiliary = _SESSION_AUXILIARY.get()
        if auxiliary is None:
            auxiliary = (load_config_readonly() or {}).get("auxiliary", {})
        auxiliary = auxiliary if isinstance(auxiliary, dict) else {}
        previous = auxiliary.get("vision", {})
        previous = previous if isinstance(previous, dict) else {}
        vision_config = {key: value for key, value in previous.items() if key not in _AUX_ROUTE_KEYS}
        scope = session_auxiliary_scope({**auxiliary, "vision": {**vision_config, **vision, "fallback_chain": []}})
        scope.__enter__()
        state["auxiliary_scope"] = scope
    agent._turn_route_task = "workload"
    logger.info("Workload route: provider=%s model=%s", agent.provider, agent.model)
    return system_prompt


def end_workload_turn_route(agent):
    state = getattr(agent, "_workload_route_state", None)
    if not state:
        return
    from agent.voice_turn_route import _reinstall
    try:
        _reinstall(agent, state)
    finally:
        if scope := state.get("auxiliary_scope"):
            scope.__exit__(None, None, None)
        agent.reasoning_config = state["reasoning_config"]
        agent._fallback_chain = state["fallback_chain"]
        agent._workload_route_state = None
        agent._turn_route_task = ""
