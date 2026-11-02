"""Memory inspection remains a read; explicit rollback uses the existing control authority."""

import pytest

from gateway.session_commands import command_verdict


@pytest.mark.parametrize("command", ["show", "history", "diff abc123"])
def test_memory_inspection_is_available_as_a_read(command):
    assert command_verdict("memory", command) == "read"


def test_memory_restore_uses_control_authority():
    assert command_verdict("memory", "restore abc123") == "control"
    assert command_verdict("memory", "unknown-command") == "refused"
