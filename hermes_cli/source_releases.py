"""Resolve promoted source releases, never infer publication from a Git tag."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import subprocess
import urllib.error
import urllib.request

from hermes_cli.update_channel import STABLE_TAG_RE, is_canary_tag

logger = logging.getLogger(__name__)
OFFICIAL_REPOSITORY = "rodos4312/Meu-Agent"
_GITHUB_ORIGIN = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$", re.IGNORECASE,
)
_SHA = re.compile(r"[0-9a-f]{40}")


def source_repository(git_cmd=None, cwd=None) -> str:
    """GitHub forks own their releases; other origins must mirror official tags."""
    if git_cmd is not None:
        from hermes_cli.source_check import source_git_env

        result = subprocess.run(
            [*git_cmd, "config", "--get", "remote.origin.url"], cwd=cwd,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            stdin=subprocess.DEVNULL, env=source_git_env(),
            check=False,
        )
        match = _GITHUB_ORIGIN.fullmatch(result.stdout.strip())
        if result.returncode == 0 and match:
            return match[1]
    return OFFICIAL_REPOSITORY


@dataclass(frozen=True)
class SourceTarget:
    """A pinned source build or an explicitly declared source-branch delivery."""

    requested_channel: str
    channel: str
    repository: str
    commit: str | None = None
    branch: str | None = None
    version: str | None = None
    build_id: str | None = None

    @property
    def retired(self) -> bool:
        return self.requested_channel != self.channel

    ahead: bool = False

    @property
    def label(self) -> str:
        if self.ahead:
            return (f"{self.channel} v{self.version}; this checkout is newer and waits for the next release"
                    " (`hermes update --set-channel main` follows every commit)")
        return f"{self.channel} v{self.version} ({self.commit[:12]})" if self.commit else self.channel




def resolve_source_target(channel: str, git_cmd=None, cwd=None, *, repository=None,
                          forward_only: bool = False) -> SourceTarget:
    """Resolve a subscription: stable from GitHub releases, main from the git branch,
    canary from published prereleases. Hosted preview channel records are retired.

    ``forward_only`` (an unchosen default subscription) pins a checkout that already
    contains the release to its own HEAD, so the update is a no-op instead of a downgrade.
    """
    target = _resolve_source_target(channel, git_cmd, cwd, repository=repository)
    if forward_only and target.commit and git_cmd is not None and cwd is not None:
        head = _head_containing(git_cmd, cwd, target.commit, target.repository)
        if head is not None and head != target.commit:
            from dataclasses import replace

            return replace(target, commit=head, ahead=True)
    return target


def _probe(git_cmd, cwd, *args):
    """``git <args>`` in ``cwd``, or None when git did not answer: an unknown relation, not a claim.

    Before the updater's fetch the release commit is usually absent, and git 2.43 spends 7-12 s
    of CPU on a blobless clone failing to find it even with lazy fetch off (#137646).
    """
    from hermes_cli.source_check import source_git_env

    try:
        return subprocess.run(
            [*git_cmd, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10, stdin=subprocess.DEVNULL, env=source_git_env(),
            check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("git %s did not answer: %s", " ".join(args), exc)
        return None


def _head_containing(git_cmd, cwd, commit: str, repository: str) -> str | None:
    """HEAD's sha unless HEAD is PROVEN not to contain ``commit``, then None.

    An unchosen default must never move a checkout backward on a guess, so an
    unknown relation (shallow history, GitHub unreachable) keeps HEAD.
    """
    from hermes_cli.source_check import _github_compare, source_git_env

    head = subprocess.run(
        [*git_cmd, "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=10, stdin=subprocess.DEVNULL, env=source_git_env(), check=False,
    ).stdout.strip()
    if not _SHA.fullmatch(head):
        return None
    # An unanswered probe falls through to the comparison API, as a shallow checkout's does.
    ancestry = _probe(git_cmd, cwd, "merge-base", "--is-ancestor", commit, head)
    if ancestry is not None and ancestry.returncode == 0:
        return head
    # A shallow boundary makes exit 1 a guess; full history makes it proof.
    if ancestry is not None and ancestry.returncode == 1:
        shallow = _probe(git_cmd, cwd, "rev-parse", "--is-shallow-repository")
        if shallow is not None and shallow.stdout.strip() == "false":
            return None
    status = (_github_compare(commit, head, repository) or {}).get("status")
    return None if status in ("behind", "diverged") else head


def _resolve_source_target(channel: str, git_cmd=None, cwd=None, *, repository=None) -> SourceTarget:
    from hermes_cli.release_channels import validate_name

    validate_name(channel)
    repository = repository or source_repository(git_cmd, cwd)
    if channel == "stable":
        return _resolve_stable(repository, git_cmd, cwd)
    if channel == "main":
        # main IS the git branch. No R2 record is read: none was ever published, and a
        # network that answers it with 403 instead of 404 (regional WAFs) must not stop
        # an install from following the branch it is on.
        return SourceTarget(channel, channel, repository, branch="main")
    if channel == "canary":
        tag, commit = _resolve_release(channel, git_cmd, cwd, repository=repository)
        return SourceTarget(channel, channel, repository, commit=commit, version=tag.removeprefix("v"))
    raise ValueError(f"Unsupported source channel: {channel}. Use stable or main; desktop previews use Meu updates.")


def _describe_release_failure(failure: BaseException) -> str:
    """A transport failure names its cause (a rate limit is not "no release")."""
    if isinstance(failure, (urllib.error.URLError, TimeoutError)):
        from hermes_cli.github_api import describe_github_failure

        # The request that failed, not the configuration: a rejected token retries anonymously.
        return describe_github_failure(failure, authenticated=getattr(failure, "hermes_authenticated", False))
    return f"No published stable release could be verified: {failure}"


def _resolve_stable(repository: str, git_cmd=None, cwd=None) -> SourceTarget:
    """Stable IS the repository's latest published GitHub release: the tag a release
    publishes (non-draft, non-prerelease, strict vX.Y.Z), verified against origin.
    No R2 record or pointer is consulted; publishing the release is the only promotion.
    """
    try:
        tag, commit = _resolve_release("stable", git_cmd, cwd, repository=repository)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.warning("Could not resolve the stable source release: %s", exc)
        raise ValueError(_describe_release_failure(exc)) from exc
    return SourceTarget("stable", "stable", repository, commit=commit, version=str(tag).removeprefix("v"))






def _valid_tag(tag, channel: str) -> bool:
    if not isinstance(tag, str):
        return False
    return bool(STABLE_TAG_RE.fullmatch(tag)) if channel == "stable" else (
        tag == tag.strip() and is_canary_tag(tag)
    )


def _published(release, channel: str) -> bool:
    return (isinstance(release, dict) and release.get("draft") is False
            and release.get("prerelease") is (channel == "canary")
            and _valid_tag(release.get("tag_name"), channel))


def _json(url: str):
    """GitHub API JSON with the updater's credential ladder (token, gh, anonymous).

    Anonymous api.github.com is 60 requests/hour per address, so an unauthenticated
    stable lookup fails for everyone behind one office, CI or container exit.
    """
    from hermes_cli.source_check import _request

    return json.loads(_request(url))


def _published_fallback(channel: str, base: str) -> dict:
    if channel == "stable":
        release = _json(f"{base}/releases/latest")
        if _published(release, channel):
            return release
    else:
        # GitHub lists newest releases first. Bound the scan; failure must
        # never turn into an arbitrary Git-tag update.
        for page in range(1, 11):
            entries = _json(f"{base}/releases?per_page=100&page={page}")
            if not isinstance(entries, list):
                break
            for release in entries:
                if _published(release, channel):
                    return release
            if len(entries) < 100:
                break
    raise ValueError(f"No published {channel} release")




def _resolve_release(channel: str, git_cmd=None, cwd=None, *, repository=None) -> tuple[str, str]:
    """``resolve_source_release`` that raises the failure instead of returning ``(None, None)``."""
    if channel not in ("stable", "canary"):
        raise ValueError(f"Not a release channel: {channel}")
    repository = repository or source_repository(git_cmd, cwd)
    base = f"https://api.github.com/repos/{repository}"
    release = _published_fallback(channel, base)
    tag = release["tag_name"]
    if not _published(release, channel) or release["tag_name"] != tag:
        raise ValueError(f"{tag} is not a published {channel} release")
    commit = _json(f"{base}/commits/{tag}")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ValueError(f"No published commit for release {tag}")
    if git_cmd is not None:
        from hermes_cli.source_check import source_git_env

        ref = f"refs/tags/{tag}"
        result = subprocess.run(
            [*git_cmd, "ls-remote", "--tags", "origin", ref, ref + "^{}"],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=True, timeout=60, stdin=subprocess.DEVNULL,
            env=source_git_env(),
        )
        refs = dict((parts[1], parts[0]) for line in result.stdout.splitlines()
                    if len(parts := line.split()) == 2)
        if refs.get(ref + "^{}", refs.get(ref)) != sha:
            raise ValueError(f"Origin tag {tag} does not match the published release commit")
    return tag, sha


def resolve_source_release(channel: str, git_cmd=None, cwd=None, *, repository=None) -> tuple[str | None, str | None]:
    """Read published GitHub releases and verify the origin tag's exact commit."""
    try:
        return _resolve_release(channel, git_cmd, cwd, repository=repository)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.warning("Could not resolve the %s source release: %s", channel, exc)
        return None, None
