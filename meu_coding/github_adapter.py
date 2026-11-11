"""The smallest GitHub REST adapter the remote workflow needs.

Credentials come from MEU's existing ladder (``hermes_cli.github_api.github_token``: env
``GITHUB_TOKEN``/``GH_TOKEN``, then ``gh auth token``). The token is only placed in the
``Authorization`` header of the request; it is never logged, stored, returned or put into an
error message. Calls happen only when the user asks (preview, refresh, an approved action),
never on a timer.

``GitHubApi`` is the protocol the workflow uses; tests supply a fake implementation.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

API = "https://api.github.com"
TIMEOUT = 20.0


class GitHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status


class GitHubApi(Protocol):
    def repo(self, owner: str, name: str) -> dict[str, Any]: ...
    def branch_protection(self, owner: str, name: str, branch: str) -> dict[str, Any] | None: ...
    def find_pull(self, owner: str, name: str, head: str, base: str) -> dict[str, Any] | None: ...
    def create_pull(self, owner: str, name: str, *, title: str, body: str, head: str, base: str) -> dict[str, Any]: ...
    def pull(self, owner: str, name: str, number: int) -> dict[str, Any]: ...
    def reviews(self, owner: str, name: str, number: int) -> list[dict[str, Any]]: ...
    def review_comments(self, owner: str, name: str, number: int) -> list[dict[str, Any]]: ...
    def checks(self, owner: str, name: str, sha: str) -> dict[str, Any]: ...
    def merge(self, owner: str, name: str, number: int, *, sha: str, method: str) -> dict[str, Any]: ...


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


class RestGitHub:
    def __init__(self, token_provider=None) -> None:
        if token_provider is None:
            from hermes_cli.github_api import github_token

            token_provider = github_token
        self._token_provider = token_provider

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(API + path, data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "meu-coding-engine")
        token = self._token_provider()
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            message = ""
            try:
                message = str(json.loads(exc.read() or b"{}").get("message", ""))[:200]
            except (ValueError, OSError):
                message = ""
            raise GitHubError(exc.code, message or exc.reason or "request failed") from None
        return json.loads(payload) if payload else {}

    def repo(self, owner, name):
        return self._request("GET", f"/repos/{_q(owner)}/{_q(name)}")

    def branch_protection(self, owner, name, branch):
        try:
            return self._request("GET", f"/repos/{_q(owner)}/{_q(name)}/branches/{_q(branch)}/protection")
        except GitHubError as exc:
            if exc.status in (403, 404):
                return None
            raise

    def find_pull(self, owner, name, head, base):
        pulls = self._request("GET", f"/repos/{_q(owner)}/{_q(name)}/pulls?state=open&head={_q(owner + ':' + head)}"
                                     f"&base={_q(base)}")
        return pulls[0] if pulls else None

    def create_pull(self, owner, name, *, title, body, head, base):
        return self._request("POST", f"/repos/{_q(owner)}/{_q(name)}/pulls",
                             {"title": title, "body": body, "head": head, "base": base})

    def pull(self, owner, name, number):
        return self._request("GET", f"/repos/{_q(owner)}/{_q(name)}/pulls/{int(number)}")

    def reviews(self, owner, name, number):
        return self._request("GET", f"/repos/{_q(owner)}/{_q(name)}/pulls/{int(number)}/reviews")

    def review_comments(self, owner, name, number):
        return self._request("GET", f"/repos/{_q(owner)}/{_q(name)}/pulls/{int(number)}/comments")

    def checks(self, owner, name, sha):
        status = self._request("GET", f"/repos/{_q(owner)}/{_q(name)}/commits/{_q(sha)}/status")
        runs = self._request("GET", f"/repos/{_q(owner)}/{_q(name)}/commits/{_q(sha)}/check-runs")
        return {"status": status, "check_runs": runs.get("check_runs", [])}

    def merge(self, owner, name, number, *, sha, method):
        return self._request("PUT", f"/repos/{_q(owner)}/{_q(name)}/pulls/{int(number)}/merge",
                             {"sha": sha, "merge_method": method})


def default_github():
    """A client when MEU has GitHub credentials, else None (remote actions stay disabled)."""
    from meu_coding.remote_refs import github_auth_available

    return RestGitHub() if github_auth_available() else None
