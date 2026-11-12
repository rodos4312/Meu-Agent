"""The local pull-request draft: data only, nothing is sent anywhere.

The user can edit the text, cancel it, or mark it "approved for creation later". The draft is
the text the remote flow (``meu_coding.task_remote``) offers when the PR is created there, after
its own push and PR approvals; this module never contacts a remote. When no remote is
configured the draft says so plainly and invents none.
"""

from __future__ import annotations

import time
from typing import Any

NO_REMOTE = "No git remote is configured for this repository — PR creation is unavailable."
NOT_YET = "This draft is saved locally; creating the PR needs the push and PR approvals."


def remote_names(repo_root: str) -> list[str]:
    from meu_coding.workspace import git_probe

    return [line.strip() for line in git_probe(repo_root, "remote").splitlines() if line.strip()]


def build_pr_preview(*, description: str, plan_summary: str, risk: str, result: dict[str, Any],
                     integration: dict[str, Any], reviewer: dict[str, Any], remotes: list[str]) -> dict[str, Any]:
    tests = integration.get("checks") or result.get("tests") or []
    passed = sum(1 for t in tests if t.get("status") == "passed")
    failed = [t.get("check", "") for t in tests if t.get("status") == "failed"]
    title = " ".join(description.split())[:72] or "Coding change"
    body = "\n".join([
        f"## Summary\n{plan_summary or description}",
        f"\n## Why\n{description}",
        "\n## Files changed\n" + "\n".join(f"- {f}" for f in integration.get("final_files") or result["changed_files"]),
        f"\n## Tests\n{passed} passed" + (f"; failed: {', '.join(failed)}" if failed else ""),
        f"\n## Risk\n{risk}",
        f"\n## Review\n{reviewer.get('verdict', '').upper()} — {reviewer.get('rationale', '')}",
        "\n## Known limitations\nPrepared by the Meu Coding Engine; review the diff before creating a PR.",
    ])
    return {
        "title": title, "body": body, "source_branch": integration.get("branch") or result["worktree_branch"],
        "target_branch": result["target_branch"], "files": list(integration.get("final_files") or
                                                                result["changed_files"]),
        "tests": {"passed": passed, "failed": failed}, "risk": risk, "reviewer": reviewer,
        "remote_available": False, "remotes": remotes, "message": NOT_YET if remotes else NO_REMOTE,
        "status": "draft", "updated_at": round(time.time(), 3),
    }
