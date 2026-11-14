"""Adapt legacy session picks to the existing shared Auto policy, without a second router."""
import copy


def safe_policy(policy):
    """Only non-secret routing fields may travel in persisted session metadata."""
    if not isinstance(policy, dict):
        return {}
    value = {k: policy[k] for k in ('enabled', 'provider', 'routine', 'complex', 'base_model')
             if isinstance(policy.get(k), (str, bool))}
    if policy.get('routes'):
        from agent.workload_routes import explicit_routes
        value['routes'] = explicit_routes(policy)
    return copy.deepcopy(value)


def prepare_mode(config, override, *, explicit=False):
    """Return the physical runtime pick and this session's frozen Auto/manual policy.

    Old persisted rows without mode metadata inherit the profile as before. A new
    explicit pick owns its mode; the virtual Auto selector never reaches an API.
    """
    pick = dict(override) if isinstance(override, dict) else override
    if isinstance(pick, dict) and isinstance(pick.get('smart_model_routing'), dict):
        return pick, safe_policy(pick['smart_model_routing'])
    chosen = pick.get('model') if isinstance(pick, dict) else None
    is_auto = chosen in ('meu-auto', 'deepseek-auto')
    if not (explicit or (isinstance(pick, dict) and pick.get('selection_explicit')) or is_auto):
        return pick, safe_policy(config.get('smart_model_routing'))
    if not is_auto:
        return pick, {'enabled': False}
    from gateway.session_model_mode import apply_selection
    selected = copy.deepcopy(config)
    model_config = selected.get('model')
    provider = pick.get('provider') or (model_config.get('provider') if isinstance(model_config, dict) else None)
    provider = provider or (selected.get('smart_model_routing') or {}).get('provider')
    physical = apply_selection(chosen, provider, selected)
    pick['model'] = physical
    pick['provider'] = provider
    return pick, safe_policy(selected.get('smart_model_routing'))


def shown_model(model, provider, policy):
    from gateway.session_model_mode import display_model
    return display_model(model, provider, {'smart_model_routing': policy})
