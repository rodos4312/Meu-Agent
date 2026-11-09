"""Request-bound exec approval settlement for relay transports."""


def actor_for_reply(adapter, event, pending):
    """Keep a refused prompt pending and return only the bot owner's actor authority."""
    if pending.get("kind") != "exec_approval":
        return {}
    from gateway.approval_actor import approval_refusal, refusal_text, runner_admin_ids

    adapter._canonicalize(event.source)
    actor = {"actor_id": getattr(event.source, "user_id", ""), "admin_ids": runner_admin_ids(event.source)}
    if requester := approval_refusal(str(pending.get("session_key") or ""), request_id=pending.get("request_id"), **actor):
        adapter._send_lifecycle_ack(str(pending.get("chat_id") or getattr(event.source, "chat_id", "")),
                                    refusal_text(requester), adapter._prompt_reply_metadata(event))
        return None
    return actor


async def resolve_exec_approval(adapter, state, option_id, chat_id, ack_meta, labels):
    from tools.approval import resolve_gateway_approval_card

    choice = option_id if option_id in labels else "deny"
    count = resolve_gateway_approval_card(str(state.get("session_key") or ""), choice, state.get("request_id"),
                                          **(state.get("actor") or {}))
    label = labels[choice] if count else "⌛ Approval expired — no command was waiting."
    # The connector's message cannot be edited cross-platform; retain an in-channel audit ack.
    adapter._send_lifecycle_ack(chat_id, label, ack_meta)
    if count:
        adapter.resume_typing_for_chat(chat_id)
