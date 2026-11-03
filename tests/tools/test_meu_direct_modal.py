"""Modal uses the user's account; retired managed selections cannot switch billing silently."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import terminal_tool_backends as backends
from tools.tool_backend_helpers import modal_configuration_error


@pytest.fixture(autouse=True)
def isolated_account(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)

    def unexpected(*args, **kwargs):
        pytest.fail("Modal configuration must not contact Nous or perform an HTTP request")

    monkeypatch.setattr("hermes_cli.nous_account.get_nous_portal_account_info", unexpected)
    monkeypatch.setattr("tools.managed_tool_gateway.is_managed_tool_gateway_ready", unexpected)
    monkeypatch.setattr("requests.sessions.Session.request", unexpected)


@pytest.mark.parametrize("mode", [None, "auto", "direct"])
def test_direct_account_reaches_modal_builder(mode, monkeypatch):
    monkeypatch.setenv("MODAL_TOKEN_ID", "test-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "test-secret")
    created = []

    def create(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(backends, "_ModalEnvironment", create)
    monkeypatch.setattr(backends.importlib.util, "find_spec", lambda name: object())
    config = {"modal_mode": mode, "container_disk": 0, "container_cpu": 2, "container_memory": 2048}
    assert backends._check_requirements("modal", config)
    env = backends._create_environment("modal", "python:3.11", "/work", 60,
                                       container_config=config, task_id="test-task")
    assert env.cwd == "/work"
    assert created[0]["modal_sandbox_kwargs"] == {"cpu": 2, "memory": 2048}
    assert created[0]["task_id"] == "test-task"


@pytest.mark.parametrize("mode", ["managed", " managed "])
def test_retired_selection_never_charges_direct_account(mode, monkeypatch):
    monkeypatch.setenv("MODAL_TOKEN_ID", "test-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "test-secret")

    def unexpected(**kwargs):
        pytest.fail("A retired managed selection must not create a direct sandbox")

    monkeypatch.setattr(backends, "_ModalEnvironment", unexpected)
    config = {"modal_mode": mode, "container_disk": 0}
    assert not backends._check_requirements("modal", config)
    assert "hermes setup terminal" in backends.terminal_backend_unavailable_reason()
    with pytest.raises(ValueError, match="has been removed"):
        backends._create_environment("modal", "python:3.11", "/work", 60, container_config=config)


def test_missing_direct_credentials_and_invalid_mode_fail_locally():
    assert "No direct Modal credentials" in modal_configuration_error("auto")
    assert "Unsupported Modal mode" in modal_configuration_error("misspelled")


def test_modal_status_does_not_inherit_managed_entitlement():
    from hermes_cli.nous_subscription import _modal_feature

    state = _modal_feature({"backend": "modal", "modal_mode": "auto"}, True)
    assert not state.available
    assert not state.active
    assert not state.managed_by_nous
