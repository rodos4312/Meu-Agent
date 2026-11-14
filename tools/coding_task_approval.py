"""Mandatory once-only coding approval using the existing human-input transports.

Unlike generic command permissions, a coding fingerprint cannot be auto-approved by
yolo, approval mode off, or a remembered terminal allowlist.
"""
from __future__ import annotations


def ask_coding_approval(view: dict) -> str:
    from tools import approval
    from tools.approval_context import get_current_session_key, _no_user_can_answer
    from tools.approval_gateway_wait import _await_gateway_decision
    from tools.approval_prompt import prompt_dangerous_approval
    from tools.terminal_tool import _get_approval_callback

    proposal = view["approval"]
    display = (
        f"Εργασία: {view['task_id']}\nΈργο: {view['project']}\n"
        f"Πρόταση: {proposal['approval_id']}\nΑποτύπωμα: {proposal['fingerprint']}\n"
        f"Αρχεία: {', '.join(proposal.get('target_files', []))}\n"
        f"Σχέδιο: {(view.get('plan') or {}).get('summary', '')}\n"
        f"Έλεγχος: {proposal.get('review_rationale', '')}\n\n"
        f"{proposal.get('proposed_diff', '')}")
    description = "Έγκριση συγκεκριμένης πρότασης κώδικα σε απομονωμένο worktree. Χωρίς commit, push ή merge."
    session_key = get_current_session_key()
    with approval._lock:
        notify = approval._gateway_notify_cbs.get(session_key)
    if notify is not None:
        result = _await_gateway_decision(session_key, notify, {
            "command": display, "description": description,
            "pattern_key": "coding:" + proposal["fingerprint"],
            "pattern_keys": ["coding:" + proposal["fingerprint"]],
            "allow_permanent": False, "allow_session": False}, surface="gateway")
        if not result.get("resolved") or result.get("cancelled") or result.get("notify_failed"):
            return "unanswered"
        choice = result.get("choice")
    else:
        callback = _get_approval_callback()
        if callback is None or _no_user_can_answer():
            return "unanswered"
        choice = prompt_dangerous_approval(display, description, allow_permanent=False,
                                           allow_session=False, approval_callback=callback)
    if choice == "once":
        return "approve"
    return "reject" if choice == "deny" else "unanswered"
