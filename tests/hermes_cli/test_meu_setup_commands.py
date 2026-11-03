"""Retired hosted setup routes must not accept commands or open a portal."""
import argparse

import pytest

from hermes_cli.subcommands.model import build_model_parser
from hermes_cli.subcommands.setup import build_setup_parser


@pytest.mark.parametrize("arguments", [
    ["setup", "--portal"], ["setup", "telemetry"], ["model", "--portal-url", "https://example.test"],
])
def test_retired_setup_arguments_are_rejected(arguments):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers()
    build_setup_parser(commands, cmd_setup=lambda args: None)
    build_model_parser(commands, cmd_model=lambda args: None)
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(arguments)
    assert exc.value.code == 2


def test_model_oauth_browser_and_timeout_options_remain_available():
    parser = argparse.ArgumentParser()
    build_model_parser(parser.add_subparsers(), cmd_model=lambda args: None)
    args = parser.parse_args(["model", "--no-browser", "--timeout", "20"])
    assert args.no_browser and args.timeout == 20


@pytest.mark.parametrize("module", ["portal_cli", "nous_auth_keepalive"])
def test_retired_portal_modules_are_unavailable(module):
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hermes_cli." + module)


def test_main_parser_has_no_portal_command():
    from hermes_cli.main import _build_cli_parser

    parser, _ = _build_cli_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["portal"])
    assert exc.value.code == 2
