"""Instructions used only in the compaction summary request, outside the cached prefix."""

EPISTEMIC_STANCE_RULE = (
    "Never turn a suspicion, working hypothesis, or unverified inference into a fact. "
    "Preserve unresolved claims with their evidence under Unverified / Working Hypotheses. "
    "Promote a claim to a finding only if the conversation provides confirmation. "
)
UNVERIFIED_HYPOTHESES_SECTION = """

## Unverified / Working Hypotheses
[List each unresolved claim as "UNVERIFIED: <claim> - <basis so far>". If none, write "None."]"""


def _today_for_prompt() -> str:
    """Date-only (user tz) for temporal anchoring; "" when the clock fails. Cache-safe: the summary is outside the prefix."""
    try:
        # Date-only granularity matches system_prompt.py:337 (PR #20451) and the user's configured timezone
        # via hermes_time.now(). The compaction summary is a mid-conversation message that is NOT part of
        # the cached prefix, so a date here never affects prompt-cache stability. Resolved defensively — a
        # clock failure must never block compaction.
        from hermes_time import now as _hermes_now
        return _hermes_now().strftime("%Y-%m-%d")
    except Exception:  # pragma: no cover - clock resolution is best-effort
        return ""
