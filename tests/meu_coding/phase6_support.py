"""Phase 6 helpers: an INTEGRATED task whose repository has a LOCAL bare remote, and a fake
GitHub that reads and updates that bare repository like the real service would.

Nothing here reaches the network or any real GitHub repository: the remote is a temporary
bare repository under ``tmp_path`` and the GitHub identity is injected for that exact URL.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from meu_coding.task_service import CodingTaskService, ModelBundle
from tests.meu_coding.phase3_support import ScriptedModel, fake_adapter, fake_runner, git, good
from tests.meu_coding.phase5_support import committed

OWNER, NAME = "meu-test", "calc"


def bare(path: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def bare_commit(remote: Path, base: str, message: str) -> str:
    """A commit on the remote (as someone else would push it): same tree as ``base``, parent ``base``."""
    tree = bare(remote, "rev-parse", f"{base}^{{tree}}")
    return bare(remote, "-c", "user.name=Other", "-c", "user.email=other@example.invalid", "commit-tree", tree,
                "-p", bare(remote, "rev-parse", base), "-m", message)


class FakeGitHub:
    """The GitHubApi protocol over a local bare repository."""

    def __init__(self, remote: Path, *, push=True, methods=("squash", "merge")) -> None:
        self.remote = remote
        self.push = push
        self.methods = methods
        self.pulls: dict[int, dict] = {}
        self.statuses: list[dict] = []
        self.runs: list[dict] = []
        self.review_list: list[dict] = []
        self.comments: list[dict] = []
        self.mergeable: bool | None = True
        self.calls: list[str] = []
        self.merge_result: dict | None = None

    def _sha(self, branch: str) -> str:
        try:
            return bare(self.remote, "rev-parse", f"refs/heads/{branch}")
        except subprocess.CalledProcessError:
            return ""

    def repo(self, owner, name):
        self.calls.append("repo")
        assert (owner, name) == (OWNER, NAME)
        return {"permissions": {"push": self.push}, "default_branch": "main",
                "allow_squash_merge": "squash" in self.methods, "allow_merge_commit": "merge" in self.methods,
                "allow_rebase_merge": "rebase" in self.methods}

    def branch_protection(self, owner, name, branch):
        return None

    def find_pull(self, owner, name, head, base):
        self.calls.append("find_pull")
        return next((p for p in self.pulls.values() if p["head"]["ref"] == head and p["base"]["ref"] == base
                     and p["state"] == "open"), None)

    def create_pull(self, owner, name, *, title, body, head, base):
        self.calls.append("create_pull")
        number = len(self.pulls) + 1
        self.pulls[number] = {"number": number, "id": 1000 + number, "html_url": f"https://example.invalid/pull/{number}",
                              "title": title, "body": body, "state": "open", "draft": False, "merged": False,
                              "created_at": "2026-11-11T00:00:00Z", "user": {"login": "meu-user"},
                              "head": {"ref": head, "sha": self._sha(head)}, "base": {"ref": base, "sha": self._sha(base)}}
        return dict(self.pulls[number])

    def pull(self, owner, name, number):
        self.calls.append("pull")
        pr = self.pulls[int(number)]
        if not pr["merged"]:
            pr["head"]["sha"] = self._sha(pr["head"]["ref"])
            pr["base"]["sha"] = self._sha(pr["base"]["ref"])
        return {**pr, "mergeable": self.mergeable, "mergeable_state": "clean" if self.mergeable else "dirty"}

    def reviews(self, owner, name, number):
        return list(self.review_list)

    def review_comments(self, owner, name, number):
        return list(self.comments)

    def checks(self, owner, name, sha):
        return {"status": {"statuses": list(self.statuses)}, "check_runs": list(self.runs)}

    def merge(self, owner, name, number, *, sha, method):
        self.calls.append(f"merge:{method}")
        if self.merge_result is not None:
            return self.merge_result
        pr = self.pulls[int(number)]
        if pr["head"]["sha"] != sha or self._sha(pr["head"]["ref"]) != sha:
            return {"merged": False, "message": "Head branch was modified"}
        base = pr["base"]["ref"]
        tree = bare(self.remote, "rev-parse", f"{sha}^{{tree}}")
        parents = ["-p", self._sha(base)] + (["-p", sha] if method == "merge" else [])
        commit = subprocess.run(["git", "-C", str(self.remote), "-c", "user.name=GitHub", "-c",
                                 "user.email=noreply@example.invalid", "commit-tree", tree, *parents, "-m",
                                 f"Merge PR #{number}"], capture_output=True, text=True, check=True).stdout.strip()
        bare(self.remote, "update-ref", f"refs/heads/{base}", commit)
        pr.update(merged=True, state="closed", merge_commit_sha=commit)
        return {"merged": True, "sha": commit, "message": "Pull Request successfully merged"}


def with_remote(repo: Path, tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    return remote


def remote_service(tmp_path: Path, remote: Path, *, github=None, auth=True) -> tuple[CodingTaskService, FakeGitHub]:
    hub = github or FakeGitHub(remote)
    url = str(remote)
    service = CodingTaskService(
        models_factory=lambda: ModelBundle(None, ScriptedModel([good]), None,
                                           {"architect": "fake:strong", "coder": "fake:strong",
                                            "reviewer": "fake:strong"}, "models_by_workload"),
        adapter_factory=lambda: fake_adapter(fake_runner()), spawn=lambda fn, name: fn(),
        audit_directory=tmp_path / "audit", github_factory=lambda: hub if auth else None,
        remote_identity=lambda u: (OWNER, NAME) if u == url else None, remote_auth=lambda: auth)
    return service, hub


def integrated(service: CodingTaskService, repo: Path) -> dict:
    view = committed(service, repo)
    token = service.integration_preview(view["task_id"])["integration"]["token"]
    done = service.integration_approve(view["task_id"], token=token, confirmed=True)
    assert done["stage"] == "integrated", done["error"]
    return done


def pushed(service: CodingTaskService, task_id: str) -> dict:
    preview = service.remote_preview(task_id, "push")["remote"]["push_preview"]
    return service.remote_approve(task_id, "push", fingerprint=preview["fingerprint"], confirmed=True)


def pr_opened(service: CodingTaskService, task_id: str) -> dict:
    pushed(service, task_id)
    preview = service.remote_preview(task_id, "pr")["remote"]["pr_preview"]
    return service.remote_approve(task_id, "pr", fingerprint=preview["fingerprint"], confirmed=True)
