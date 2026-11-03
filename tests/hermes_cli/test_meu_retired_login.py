"""Meu exposes supported provider authentication, never the retired Nous sign-in."""

import importlib
import socket
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("Retired sign-in attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_auth_upgrade_is_not_a_cli_command():
    from hermes_cli.main import _build_cli_parser
    parser, _ = _build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["auth", "upgrade"])
    assert exc.value.code == 2


def test_login_is_not_a_chat_command():
    from hermes_cli.commands import resolve_command
    assert resolve_command("login") is None
    assert resolve_command("model") is not None
    assert resolve_command("skills") is not None


def test_auth_add_nous_refuses_before_any_network_request():
    from hermes_cli.auth_commands import auth_add_command
    with pytest.raises(SystemExit):
        auth_add_command(SimpleNamespace(provider="nous", auth_type="oauth"))


@pytest.mark.parametrize("module", [
    "hermes_cli.anon_sign_in", "hermes_cli.anon_sign_in_cli", "gateway.slash_commands_login",
])
def test_removed_sign_in_implementation_cannot_be_imported(module):
    with pytest.raises(ModuleNotFoundError) as exc:
        importlib.import_module(module)
    assert exc.value.name == module
