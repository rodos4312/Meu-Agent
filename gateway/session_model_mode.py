"""Desktop's Auto selector is a policy choice, never a provider model ID."""

AUTO_MODEL = 'deepseek-auto'
BASE_MODEL = 'deepseek-v4-pro'


def bind_agent_mode(agent, policy, authority):
    """The constructed agent must use its session's mode, not the profile default it loaded."""
    if policy is not None:
        from agent.agent_init_request_policy import init_model_routing_policy
        init_model_routing_policy(agent, policy.config(authority, secrets=False))
    return agent


def apply_selection(model, provider, config):
    from hermes_state_runtime import RuntimeStoreError
    if model == AUTO_MODEL and provider != 'deepseek':
        raise RuntimeStoreError('invalid_params')
    if provider == 'deepseek' and model:
        config['smart_model_routing'] = {**(config.get('smart_model_routing') or {}),
                                         'enabled': model == AUTO_MODEL}
        config.setdefault('model', {})['default'] = BASE_MODEL if model == AUTO_MODEL else model
    return BASE_MODEL if model == AUTO_MODEL else model


def display_model(model, provider, config):
    return AUTO_MODEL if provider == 'deepseek' and (
        config.get('smart_model_routing') or {}).get('enabled') is True else model


def profile_auto_policy(authority):
    from gateway.session_policy import profile_config
    return dict(profile_config(authority).get('smart_model_routing') or {})


def decorate_options(payload, config):
    """Only gateways implementing session mode selection advertise the virtual selector."""
    for row in payload['providers']:
        if row['slug'] == 'deepseek' and row.get('automatic_routing') is True:
            row['models'] = [AUTO_MODEL, *[m for m in row['models'] if m != AUTO_MODEL]]
    payload['model'] = display_model(payload.get('model'), payload.get('provider'), config)
    return payload
