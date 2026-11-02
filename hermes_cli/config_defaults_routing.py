"""Pure-data routing defaults; automatic model selection is opt-in."""

ROUTING_DEFAULTS = {
    "fallback_providers": [],
    # Explicit opt-in: provider-local main-request routing; auxiliary tasks keep their own model.
    "smart_model_routing": {"enabled": False},
    # min_switch_reset_seconds: opt-in (0 = off). When a rate-limited primary declares a reset
    # sooner than this many seconds, stay on it (the retry backoff rides out the window) instead
    # of switching the turn to a fallback model.
    "fallback": {"min_switch_reset_seconds": 0},
}
