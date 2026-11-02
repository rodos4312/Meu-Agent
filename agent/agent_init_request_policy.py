"""Frozen per-session request policies; the agent-init facade retains the cache helper binding."""

import logging

logger = logging.getLogger("run_agent")


def init_model_routing_policy(agent, config):
    routing = config.get("smart_model_routing")
    agent._model_routing_config = dict(routing) if isinstance(routing, dict) else {}


def _init_prompt_cache_config(agent):
    # Anthropic prompt caching (~75% input savings): auto-enabled for Claude on native
    # Anthropic, OpenRouter and anthropic_messages gateways. See _anthropic_prompt_cache_policy.
    agent._use_prompt_caching, agent._use_native_cache_layout = (
        agent._anthropic_prompt_cache_policy()
    )
    agent._cache_disabled = False
    # cache_ttl: "5m" (default), "1h" (2x write cost; pays off with >5-minute pauses) or "auto"
    # (1h when a person paces the session, 5m when a machine does); unknown values keep "5m". A falsy/off value disables caching entirely (OAuth plans
    # billing cache writes, proxies adding their own cache_control); the disable survives
    # /model switches and fallback re-derivation.
    # Anthropic supports "5m" (default) and "1h" cache TTL tiers. Read from config.yaml under
    # prompt_caching.cache_ttl; unknown values keep "5m". 1h tier costs 2x on write vs 1.25x for 5m, but
    # amortizes across long sessions with >5-minute pauses between turns (#14971). This is useful for OAuth
    # subscription users where cache writes bill against "extra usage" or for third-party proxies that
    # inject their own cache_control markers (#13477).
    agent._cache_ttl = "5m"
    try:
        from hermes_cli.config import load_config_readonly as _load_pc_cfg
        from agent.agent_runtime_helpers import cache_ttl_means_disabled
        from agent.prompt_caching import AUTO_CACHE_TTL, auto_cache_ttl_for_source
        _pc_cfg = _load_pc_cfg().get("prompt_caching", {}) or {}
        _ttl = _pc_cfg.get("cache_ttl", "5m")
        if _ttl in {"5m", "1h"}:
            agent._cache_ttl = _ttl
        elif _ttl == AUTO_CACHE_TTL:
            # Decided once per session from its source (a delegated child is clamped to 5m again
            # in delegate_tool regardless).
            from agent.session_source import session_source_for
            agent._cache_ttl = auto_cache_ttl_for_source(session_source_for(getattr(agent, "platform", None)))
        elif cache_ttl_means_disabled(_ttl):
            agent._use_prompt_caching = False
            agent._use_native_cache_layout = False
            agent._cache_ttl = None
            agent._cache_disabled = True
    except Exception as exc:  # health: allow BLE001 -- init must survive any config failure; the class is logged
        # Config values and traceback frames may contain credentials.
        logger.warning(
            "Agent configuration for prompt_caching.cache_ttl could not be loaded (%s); "
            "using default prompt caching settings. Check the active Hermes Python "
            "environment and dependencies; run 'hermes config check' after "
            "configuration imports work again.",
            type(exc).__name__,
        )

