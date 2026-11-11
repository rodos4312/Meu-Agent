"""Desktop's Auto selector is a policy choice, never a provider model ID."""

AUTO_MODEL = 'deepseek-auto'
GENERAL_AUTO_MODEL = 'meu-auto'
BASE_MODEL = 'deepseek-v4-pro'


def bind_agent_mode(agent, policy, authority):
    """The constructed agent must use its session's mode, not the profile default it loaded."""
    if policy is not None:
        from agent.agent_init_request_policy import init_model_routing_policy
        init_model_routing_policy(agent, policy.config(authority, secrets=False))
    return agent


def apply_selection(model, provider, config):
    from agent.model_routing_policy import selected_pair
    from hermes_state_runtime import RuntimeStoreError
    if model == AUTO_MODEL and provider != 'deepseek':
        raise RuntimeStoreError('invalid_params')
    if model == GENERAL_AUTO_MODEL:
        pair = selected_pair(config.get('smart_model_routing'), provider)
        if pair is None:
            raise RuntimeStoreError('invalid_params')
        config['smart_model_routing'] = {**config['smart_model_routing'], 'enabled': True}
        config.setdefault('model', {})['default'] = pair[1]
        return pair[1]
    if provider == 'deepseek' and model:
        config['smart_model_routing'] = {**(config.get('smart_model_routing') or {}),
                                         'enabled': model == AUTO_MODEL}
        if model == AUTO_MODEL:
            config['smart_model_routing'].update(provider='deepseek',
                                                routine='deepseek-flash', complex=BASE_MODEL)
        config.setdefault('model', {})['default'] = BASE_MODEL if model == AUTO_MODEL else model
    elif model and config.get('smart_model_routing'):
        config['smart_model_routing'] = {**(config.get('smart_model_routing') or {}), 'enabled': False}
    return BASE_MODEL if model == AUTO_MODEL else model


def display_model(model, provider, config):
    from agent.model_routing_policy import selected_pair
    policy = config.get('smart_model_routing') or {}
    if policy.get('enabled') is not True:
        return model
    if provider == 'deepseek' and not policy.get('routes'):
        return AUTO_MODEL
    return GENERAL_AUTO_MODEL if selected_pair(policy, provider) else model


def profile_auto_policy(authority):
    from gateway.session_policy import profile_config
    return dict(profile_config(authority).get('smart_model_routing') or {})


def decorate_options(payload, config):
    """Only gateways implementing session mode selection advertise the virtual selector."""
    for row in payload['providers']:
        from agent.workload_routes import auto_routes_available
        if auto_routes_available(config.get('smart_model_routing'), row['slug']):
            row['automatic_routing'] = True
            row['models'] = [GENERAL_AUTO_MODEL, *[m for m in row['models'] if m not in (GENERAL_AUTO_MODEL, AUTO_MODEL)]]
        elif row['slug'] == 'deepseek' and row.get('automatic_routing') is True:
            row['models'] = [AUTO_MODEL, *[m for m in row['models'] if m != AUTO_MODEL]]
        elif row['slug'] != 'deepseek':
            from agent.model_routing_policy import selected_pair
            if selected_pair(config.get('smart_model_routing'), row['slug']):
                row['automatic_routing'] = True
                row['models'] = [GENERAL_AUTO_MODEL, *[m for m in row['models'] if m != GENERAL_AUTO_MODEL]]
    payload['model'] = display_model(payload.get('model'), payload.get('provider'), config)
    return payload
