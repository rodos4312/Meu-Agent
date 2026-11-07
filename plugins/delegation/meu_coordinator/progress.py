"""Small, read-only display receipts shared by chat and workspace clients."""
from pathlib import Path

from tools.delegation_redaction import redact_child_text

from .reviews import review_snapshot

STATES = {"pending", "running", "interrupted", "needs_review", "verified", "failed"}


def _text(value, limit=6000):
    if not isinstance(value, str) or not value.strip():
        return None
    # Display projections never carry raw child output, arguments or context.
    clean = redact_child_text(value)
    return clean if len(clean) <= limit else clean[:limit] + "…"


def artifact_files(root, names):
    files = []
    for name in names:
        if not isinstance(name, str):
            continue
        relative = Path(name)
        if relative.is_absolute():
            continue
        file = root / relative
        if file.is_symlink():
            continue
        path = file.resolve()
        if path.is_relative_to(root) and path.is_file():
            files.append({"name": name, "path": str(path)})
    return files


def project_progress(record, *, idle=False):
    """Use checkpoint states; successful helper output alone never means verified."""
    root = Path(record["root"]).resolve()
    tasks = []
    for key, row in record["tasks"].items():
        task = row["task"]
        status = row["state"]
        if status not in STATES:
            continue
        if status == "running" and idle:
            status = "interrupted"
        result = (row.get("result") or {}) if status in {"needs_review", "verified", "failed"} else {}
        route = result.get("route") or {}
        finding = review_snapshot(record, row)
        review = None if finding is None else {
            "verdict": finding["verdict"], "check": _text(finding["check"], 400),
            "observed": _text(finding["observed"], 1200), "reviewed_attempt": finding["reviewed_attempt"],
        }
        tasks.append({
            "id": key, "goal": _text(task["goal"], 2000) or key, "state": status,
            "attempt": row.get("attempt", 0), "acceptance": _text(task.get("acceptance")),
            "workload": task.get("workload"), "depends_on": list(task.get("depends_on", [])),
            "review_of": task.get("review_of"),
            "evidence": _text(row.get("evidence")) if status in {"needs_review", "verified", "failed"} else None,
            "repair_check": _text((row.get("repair") or {}).get("check"), 400),
            "error": _text(row.get("error"), 1200), "review": review,
            "provider": _text(route.get("provider"), 120),
            "model": _text(route.get("model") or result.get("model"), 240),
            "artifacts": artifact_files(root, row.get("artifacts") or {}) if status == "verified" else [],
        })
    return tasks
