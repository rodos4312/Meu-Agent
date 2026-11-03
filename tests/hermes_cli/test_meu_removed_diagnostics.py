"""Retired Nous upload requests cannot fall through to another upload service."""

import argparse
from unittest.mock import Mock

import pytest

from hermes_cli.subcommands.debug import build_debug_parser


def test_nous_option_is_rejected_before_debug_dispatch():
    parser = argparse.ArgumentParser()
    dispatch = Mock()
    build_debug_parser(parser.add_subparsers(), cmd_debug=dispatch)
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["debug", "share", "--nous", "--yes"])
    assert error.value.code == 2
    dispatch.assert_not_called()


@pytest.mark.parametrize("command", ["/debug nous", "/debug NOUS", "/debug unknown"])
def test_retired_slash_destination_never_falls_through_to_public_upload(command, monkeypatch):
    from hermes_cli import debug
    from hermes_cli.cli_commands_mixin import CLICommandsMixin

    upload = Mock(side_effect=AssertionError("Unexpected upload dispatch"))
    monkeypatch.setattr(debug, "run_debug_share", upload)
    CLICommandsMixin._handle_debug_command(object(), command)
    upload.assert_not_called()
