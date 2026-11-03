"""Old transcripts keep readable tool labels after hosted execution is removed."""
import pytest
from tools.connectors.legacy_names import parse_connector_name

@pytest.mark.parametrize("raw,connector,tool", [
    ("connectors__gmail__GET_PROFILE", "gmail", "GET_PROFILE"),
    ("connectors__better_stack_mcp__ACKNOWLEDGE_INCIDENT", "better_stack_mcp", "ACKNOWLEDGE_INCIDENT"),
    ("connectors__granola__MCP_GET_MEETINGS", "granola", "MCP_GET_MEETINGS"),
])
def test_saved_names_keep_the_service_and_action(raw, connector, tool):
    parsed = parse_connector_name(raw)
    assert parsed and (parsed.connector, parsed.tool) == (connector, tool)

@pytest.mark.parametrize("raw", [None, "connectors__execute", "connectors____READ", "mcp__paper__read"])
def test_invalid_or_other_names_are_not_legacy_connectors(raw):
    assert parse_connector_name(raw) is None
