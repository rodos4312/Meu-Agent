"""Legacy key blocking: retired upstream credentials never reach any child process.

Meu has no Nous provider. ``NOUS_API_KEY`` and the old portal/inference URL overrides are kept
only on a deny list, so a value left in a user's shell or old ``.env`` is stripped from every
child environment — including the paths that otherwise let provider credentials through.
"""
import pytest

from tests.tools._child_env_fixtures import child_env, observe_child
from tools.environments import local
from tools.environments.local_env_policy import RETIRED_CREDENTIAL_ENV, strip_retired_credentials

RETIRED = sorted(RETIRED_CREDENTIAL_ENV)


def _seed(monkeypatch):
    for name in RETIRED:
        monkeypatch.setenv(name, "leftover-" + name)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai")


@pytest.mark.usefixtures(child_env.__name__)
@pytest.mark.parametrize("inherit_credentials", [False, True])
def test_retired_credentials_never_reach_a_sanitized_child(monkeypatch, inherit_credentials):
    _seed(monkeypatch)
    observed = observe_child(local.hermes_subprocess_env(inherit_credentials=inherit_credentials),
                             [*RETIRED, "OPENAI_API_KEY"])
    assert {name: observed[name] for name in RETIRED} == dict.fromkeys(RETIRED)
    # Control: the grant still works for a supported provider key.
    assert observed["OPENAI_API_KEY"] == ("fake-openai" if inherit_credentials else None)


@pytest.mark.usefixtures(child_env.__name__)
def test_passthrough_and_caller_extras_cannot_bring_a_retired_credential_back(monkeypatch):
    from tools.env_passthrough import register_env_passthrough

    _seed(monkeypatch)
    register_env_passthrough(RETIRED)
    env = local.build_subprocess_env(scrub_secrets=False, extra={"NOUS_API_KEY": "explicit"})
    assert not set(env) & RETIRED_CREDENTIAL_ENV
    env = local.build_subprocess_env(extra={"NOUS_API_KEY": "explicit"})
    assert not set(env) & RETIRED_CREDENTIAL_ENV


def test_strip_is_case_folded_for_the_windows_env_block():
    env = {"nous_api_key": "x", "Nous_Inference_Base_Url": "y", "PATH": "p"}
    assert strip_retired_credentials(env) == {"PATH": "p"}


def test_retired_names_are_not_a_supported_provider():
    """Blocking a name must never mean supporting it: no registered provider reads these."""
    from hermes_cli.auth import PROVIDER_REGISTRY

    assert "nous" not in PROVIDER_REGISTRY
    for pconfig in PROVIDER_REGISTRY.values():
        assert not set(pconfig.api_key_env_vars) & RETIRED_CREDENTIAL_ENV
        assert pconfig.base_url_env_var not in RETIRED_CREDENTIAL_ENV
