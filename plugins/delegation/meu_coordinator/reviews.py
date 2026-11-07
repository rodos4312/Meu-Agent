"""Bind an independent review to the exact accepted version of one task."""

import json

from tools.delegation_output_schema import extract_json_candidate


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["pass", "needs_fix", "inconclusive"]},
        "check": {"type": "string", "minLength": 1, "maxLength": 400},
        "observed": {"type": "string", "minLength": 1, "maxLength": 1200},
    },
    "required": ["verdict", "check", "observed"],
    "additionalProperties": False,
}


def configure_review(state, row, task):
    target_id = row["task"].get("review_of")
    if target_id is None:
        return
    target = state.record["tasks"][target_id]
    row["reviewed_attempt"] = target["attempt"]
    row["reviewed_artifacts"] = target.get("artifacts", {})
    task["output_schema"] = REVIEW_SCHEMA
    task["context"] += (
        f"\nIndependently review {target_id}, attempt {target['attempt']}. "
        f"Acceptance check: {target['task']['acceptance']}. "
        f"Recorded artifacts: {json.dumps(target.get('artifacts', {}), ensure_ascii=False)}. "
        "Report the exact check or reproduction steps and the observed result. "
        "Use inconclusive if you lack evidence. Do not edit the deliverable."
    )
    if repair := target.get("repair"):
        task["context"] += f"\nRepeat the confirmed repair check: {repair['check']}"


def review_finding(state, reviewer):
    target_id = reviewer["task"].get("review_of")
    if target_id is None or reviewer["state"] != "needs_review":
        raise ValueError("Use the current completed independent review.")
    return _current_finding(state.record, reviewer)


def _current_finding(record, reviewer):
    target = record["tasks"][reviewer["task"]["review_of"]]
    if (target["state"] != "verified" or reviewer.get("reviewed_attempt") != target["attempt"]
            or reviewer.get("reviewed_artifacts") != target.get("artifacts", {})):
        raise ValueError("The reviewed deliverable changed; retry the review after verifying the current attempt.")
    result = reviewer.get("result") or {}
    if result.get("schema_valid") is not True or result.get("truncated"):
        raise ValueError("The reviewer did not return a validated finding.")
    try:
        finding = json.loads(extract_json_candidate(result.get("summary") or ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("The reviewer did not return a readable finding.") from exc
    if not isinstance(finding, dict) or any(
        not isinstance(finding.get(key), str) or not finding[key].strip() for key in ("check", "observed")
    ):
        raise ValueError("The reviewer must report a concrete check and observation.")
    return target, finding


def review_snapshot(record, reviewer):
    """A display receipt is not permission to accept a task or replay a helper."""
    if not reviewer["task"].get("review_of") or reviewer["state"] not in {"needs_review", "verified"}:
        return None
    try:
        _, finding = _current_finding(record, reviewer)
    except (ValueError, KeyError, TypeError):
        return None
    if finding.get("verdict") not in {"pass", "needs_fix", "inconclusive"}:
        return None
    return {**finding, "reviewed_attempt": reviewer["reviewed_attempt"]}


def request_fix(state, reviewer, evidence):
    target, finding = review_finding(state, reviewer)
    if finding.get("verdict") != "needs_fix":
        raise ValueError("A repair requires a reproduced failure in the review.")
    if max(target["attempt"], reviewer["attempt"]) >= 3:
        raise ValueError("The deliverable or reviewer has reached its three-attempt limit.")
    target["repair"] = {
        "reviewed_attempt": target["attempt"], "check": finding["check"],
        "observed": finding["observed"], "evidence": evidence,
    }
    target.update(state="pending", artifacts={})
    target.pop("error", None)
    target["task"]["workload"] = "complex"
    reviewer.update(state="pending", evidence=evidence)
    state.refresh()
