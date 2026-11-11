"""Remote detection and strict validation of every name that reaches a remote git command.

Nothing here invents or configures a remote. A remote is usable only when it exists, its
configured push URL equals its fetch URL and the effective URL git would use (an ``insteadOf``
or ``pushurl`` rewrite is refused as URL substitution), and the remote and branch names pass
allowlist validation plus ``git check-ref-format``. Credentials are only ever probed for
presence through MEU's existing ladder (``hermes_cli.github_api``); a token never leaves it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from meu_coding.integration import git

SAFE_REMOTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
# Pushing into these is never offered by the Coding Engine, whatever the repository says.
FORBIDDEN_DESTINATIONS = frozenset({"main", "master", "trunk", "develop", "production", "release"})
PUSHABLE_PREFIXES = ("hermes-subagent/",)
logger = logging.getLogger(__name__)
_GITHUB = (
    re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"),
    re.compile(r"^git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$"),
    re.compile(r"^ssh://git@github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$"),
)


class RemoteRefused(Exception):
    pass


def validate_remote_name(name: str) -> str:
    if not isinstance(name, str) or not SAFE_REMOTE.match(name):
        raise RemoteRefused(f"Invalid remote name {name!r}.")
    return name


def validate_branch(repo: str, name: str) -> str:
    """Allowlist first (no option-looking, refspec or revision syntax), then git's own rules."""
    bad = ("..", "@{", "//", ".lock", "~", "^", ":", "?", "*", "[", "\\", " ")
    if not isinstance(name, str) or not SAFE_BRANCH.match(name) or any(b in name for b in bad) \
            or name.endswith(("/", ".")):
        raise RemoteRefused(f"Invalid branch name {name!r}.")
    if git(repo, "check-ref-format", "--branch", name).returncode != 0:
        raise RemoteRefused(f"Git rejects the branch name {name!r}.")
    return name


def validate_sha(value: str) -> str:
    if not isinstance(value, str) or not SHA.match(value):
        raise RemoteRefused("Invalid commit id.")
    return value


def parse_github(url: str) -> tuple[str, str] | None:
    for pattern in _GITHUB:
        match = pattern.match(url or "")
        if match:
            owner, name = match.group(1), match.group(2)
            return None if owner.startswith(".") or name.startswith(".") else (owner, name)
    return None


@dataclass
class RemoteInfo:
    available: bool
    reason: str = ""
    name: str = ""
    url: str = ""
    owner: str = ""
    repo: str = ""
    is_github: bool = False
    auth_available: bool = False
    push_allowed: bool | None = None
    default_branch: str = ""
    merge_methods: list[str] = field(default_factory=list)
    protected: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        return f"github.com/{self.owner}/{self.repo}" if self.is_github else self.url

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["identity"] = self.identity
        return data


def _config(repo: str, key: str) -> list[str]:
    out = git(repo, "config", "--get-all", key)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()] if out.returncode == 0 else []


def _choose_remote(repo: str) -> str:
    names = [line.strip() for line in git(repo, "remote").stdout.splitlines() if line.strip()]
    if not names:
        raise RemoteRefused("No git remote is configured for this repository — remote actions are unavailable.")
    if "origin" in names:
        return "origin"
    if len(names) == 1:
        return names[0]
    raise RemoteRefused("Several remotes are configured and none is named origin — remote actions are unavailable.")


def _url(repo: str, name: str) -> str:
    fetch = _config(repo, f"remote.{name}.url")
    push = _config(repo, f"remote.{name}.pushurl") or fetch
    effective = git(repo, "remote", "get-url", "--push", name).stdout.strip()
    if len(fetch) != 1 or len(push) != 1:
        raise RemoteRefused("The remote has several URLs — remote actions are unavailable.")
    if push[0] != fetch[0] or effective != fetch[0]:
        raise RemoteRefused("The remote's push URL differs from its fetch URL (or is rewritten) — "
                            "remote actions are unavailable.")
    return fetch[0]


def github_auth_available() -> bool:
    from hermes_cli.github_api import github_token

    return github_token() is not None


def detect_remote(repo: str, *, github=None, identity: Callable[[str], tuple[str, str] | None] = parse_github,
                  auth_available: Callable[[], bool] = github_auth_available) -> RemoteInfo:
    try:
        name = validate_remote_name(_choose_remote(repo))
        url = _url(repo, name)
    except RemoteRefused as exc:
        return RemoteInfo(False, str(exc))
    owner_repo = identity(url)
    info = RemoteInfo(True, "", name, url, *(owner_repo or ("", "")), is_github=owner_repo is not None)
    if not info.is_github:
        info.available, info.reason = False, "The remote is not a GitHub repository — remote actions are unavailable."
        return info
    info.auth_available = bool(auth_available())
    if not info.auth_available or github is None:
        info.reason = "No GitHub credentials are available to Meu — remote actions stay disabled."
        info.available = False
        return info
    _read_repo_settings(info, github)
    return info


def _read_repo_settings(info: RemoteInfo, github) -> None:
    try:
        settings = github.repo(info.owner, info.repo)
    except Exception as exc:  # any API failure keeps remote actions disabled, with the reason shown
        logger.warning("GitHub repository settings unavailable", exc_info=True)
        info.available, info.reason = False, f"GitHub could not be reached: {type(exc).__name__}"
        return
    permissions = settings.get("permissions") or {}
    info.push_allowed = bool(permissions.get("push")) if permissions else None
    info.default_branch = str(settings.get("default_branch") or "")
    info.merge_methods = [m for m, key in (("merge", "allow_merge_commit"), ("squash", "allow_squash_merge"),
                                           ("rebase", "allow_rebase_merge")) if settings.get(key)]
    if info.push_allowed is False:
        info.available, info.reason = False, "These credentials cannot push to the repository."


def remote_branch_sha(repo: str, remote: str, branch: str) -> str:
    """The branch head on the remote ("" when absent). Read-only."""
    out = git(repo, "ls-remote", "--heads", validate_remote_name(remote), f"refs/heads/{branch}")
    if out.returncode != 0:
        raise RemoteRefused(f"Could not read the remote: {out.stderr.strip()[:200]}")
    for line in out.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == f"refs/heads/{branch}":
            return sha.strip()
    return ""
