"""Slack and QQ callbacks enforce the captured requester, not just chat admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.gateway.test_approval_requester_binding import DEFAULT, pending_from, write_approvers


@pytest.fixture(autouse=True)
def clean_queues():
    from tools import approval

    approval._gateway_queues.clear()
    yield
    approval._gateway_queues.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(("approvers", "allowed"), [(DEFAULT, True), ([], False)])
async def test_slack_requester_binding(approvers, allowed):
    from tests.gateway.test_slack_approval_buttons import _attach_auth_runner, _make_adapter

    write_approvers(approvers)
    entry = pending_from("alice", "Alice", "sess-slack", platform="slack")
    adapter = _make_adapter()
    _attach_auth_runner(adapter)
    adapter._approval_resolved["1.2"] = False
    client = adapter._team_clients["T1"]
    client.chat_update = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
    body = {"message": {"ts": "1.2", "blocks": []}, "channel": {"id": "C1"},
            "user": {"name": "Bob", "id": "bob"}}
    action = {"action_id": "hermes_approve_once", "value": f"sess-slack|{entry.data['request_id']}"}
    await adapter._handle_approval_action(AsyncMock(), body, action)
    assert entry.event.is_set() is allowed
    if not allowed:
        assert adapter._approval_resolved["1.2"] is False
        assert client.chat_postEphemeral.call_args.kwargs["user"] == "bob"
        body["user"] = {"name": "Alice", "id": "alice"}
        await adapter._handle_approval_action(AsyncMock(), body, action)
    assert entry.result == "once"


@pytest.mark.asyncio
@pytest.mark.parametrize(("approvers", "allowed"), [(DEFAULT, True), ([], False)])
async def test_qq_requester_binding(monkeypatch, approvers, allowed):
    from gateway.config import PlatformConfig
    from plugins.platforms.qqbot.adapter import QQAdapter

    write_approvers(approvers)
    entry = pending_from("alice", "Alice", "sess-qq", platform="qqbot")
    adapter = QQAdapter(PlatformConfig(enabled=True, extra={"app_id": "fixture", "client_secret": "fixture"}))
    # Both users already passed platform admission; the approval's actor is a separate boundary.
    monkeypatch.setattr(adapter, "_is_authorized_interaction_for_session", lambda *_: True)
    event = SimpleNamespace(button_data=f"approve:sess-qq|{entry.data['request_id']}:allow-once",
                            operator_openid="bob")
    await adapter._default_interaction_dispatch(event)
    assert entry.event.is_set() is allowed
    if not allowed:
        event.operator_openid = "alice"
        await adapter._default_interaction_dispatch(event)
    assert entry.result == "once"


def test_authority_is_frozen_in_the_requesting_profile(tmp_path):
    from gateway.approval_actor import may_answer
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    owner = tmp_path / "owner"
    routed = tmp_path / "routed"
    owner.mkdir()
    routed.mkdir()
    token = set_hermes_home_override(owner)
    try:
        write_approvers(["owner-helper"])
        entry = pending_from("alice", "Alice", "sess-owner")
        write_approvers(["*"])
        routed_token = set_hermes_home_override(routed)
        try:
            write_approvers(["routed-helper"])
            other = pending_from("alice", "Alice", "sess-routed")
            assert may_answer(entry.authority, "owner-helper")
            assert not may_answer(entry.authority, "routed-helper")
            assert not may_answer(entry.authority, "bob")
            assert may_answer(other.authority, "routed-helper")
            assert not may_answer(other.authority, "owner-helper")
        finally:
            reset_hermes_home_override(routed_token)
    finally:
        reset_hermes_home_override(token)


def test_native_card_without_actor_cannot_use_trusted_host_bypass():
    from tools.approval import resolve_gateway_approval_card

    write_approvers([])
    entry = pending_from("alice", "Alice", "sess-card")
    assert resolve_gateway_approval_card("sess-card", "once", entry.data["request_id"]) == 0
    assert not entry.event.is_set()
    assert resolve_gateway_approval_card("sess-card", "once", entry.data["request_id"], actor_id="alice") == 1
