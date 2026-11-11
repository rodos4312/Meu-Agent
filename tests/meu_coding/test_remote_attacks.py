"""Phase 6 attacks on the remote workflow: option/refspec injection, URL substitution,
forbidden destinations, PR text injection, stale/foreign approvals, spoofed sources,
duplicate execution, and credential hygiene. Remote = local bare repository; GitHub = fake."""

import io
import json
import threading
import urllib.error
from pathlib import Path

import pytest

from meu_coding import remote_ops
from meu_coding.github_adapter import GitHubError, RestGitHub
from meu_coding.remote_refs import (
    RemoteRefused,
    detect_remote,
    parse_github,
    validate_branch,
    validate_remote_name,
)
from meu_coding.task_service import TaskError
from tests.meu_coding.phase3_support import git
from tests.meu_coding.phase6_support import (
    OWNER,
    NAME,
    FakeGitHub,
    bare,
    integrated,
    pr_opened,
    pushed,
    remote_service,
    with_remote,
)


@pytest.fixture
def setup(git_repo, tmp_path):
    remote = with_remote(git_repo, tmp_path)
    service, hub = remote_service(tmp_path, remote)
    view = integrated(service, git_repo)
    return service, hub, remote, view["task_id"], git_repo


def _identity(remote: Path):
    return lambda url: (OWNER, NAME) if url == str(remote) else None


@pytest.mark.parametrize("name", ["--force", "-f", "--mirror", "--all", "--tags", "--force-with-lease", "+main",
                                  "main:main", "a..b", "x@{1}", "x~1", "x^", "a b", "x.lock", "x/", "-x",
                                  "refs/heads/main:refs/heads/main", "x\\y", "x*", "x?", "x[1]", "/x", "a//b", ""])
def test_branch_option_and_refspec_injection_is_refused(git_repo, name):
    with pytest.raises(RemoteRefused):
        validate_branch(str(git_repo), name)


@pytest.mark.parametrize("name", ["--mirror", "-u", "origin --force", "../x", "a/b", "", "o" * 80, "o;rm"])
def test_remote_name_injection_is_refused(name):
    with pytest.raises(RemoteRefused):
        validate_remote_name(name)


def test_url_substitution_via_insteadof_or_pushurl_disables_remote(git_repo, tmp_path):
    remote = with_remote(git_repo, tmp_path)
    git(git_repo, "config", "remote.origin.pushurl", str(tmp_path / "attacker.git"))
    info = detect_remote(str(git_repo), github=FakeGitHub(remote), identity=_identity(remote), auth_available=lambda: True)
    assert not info.available and "differs" in info.reason
    git(git_repo, "config", "--unset", "remote.origin.pushurl")
    git(git_repo, "config", f"url.{tmp_path / 'attacker.git'}.insteadOf", str(remote))
    info = detect_remote(str(git_repo), github=FakeGitHub(remote), identity=_identity(remote), auth_available=lambda: True)
    assert not info.available and "rewritten" in info.reason


def test_several_remotes_without_origin_are_refused(git_repo, tmp_path):
    git(git_repo, "remote", "add", "upstream", str(tmp_path / "a.git"))
    git(git_repo, "remote", "add", "fork", str(tmp_path / "b.git"))
    info = detect_remote(str(git_repo), github=None, auth_available=lambda: True)
    assert not info.available and "Several remotes" in info.reason


def test_non_github_and_lookalike_urls_are_not_github():
    assert parse_github("https://github.com/o/r.git") == ("o", "r")
    assert parse_github("git@github.com:o/r.git") == ("o", "r")
    for url in ("https://github.com.evil.example/o/r", "https://evil.example/github.com/o/r",
                "https://user:pw@github.com/o/r", "http://github.com/o/r", "file:///github.com/o/r",
                "https://github.com/o/r/../x", "https://github.com/o/..", "https://github.com/../r"):
        assert parse_github(url) is None, url


def test_credentials_that_cannot_push_disable_remote(git_repo, tmp_path):
    remote = with_remote(git_repo, tmp_path)
    info = detect_remote(str(git_repo), github=FakeGitHub(remote, push=False), identity=_identity(remote),
                         auth_available=lambda: True)
    assert not info.available and "cannot push" in info.reason


@pytest.mark.parametrize("destination", ["main", "master", "release", "feature/x"])
def test_push_to_protected_or_non_integration_branch_is_refused(git_repo, tmp_path, destination):
    remote = with_remote(git_repo, tmp_path)
    if destination != "main":
        git(git_repo, "branch", destination)
    info = detect_remote(str(git_repo), github=FakeGitHub(remote), identity=_identity(remote),
                         auth_available=lambda: True)
    with pytest.raises(RemoteRefused, match="not allowed|Only integration branches"):
        remote_ops.push_preview(repo=str(git_repo), info=info, source_branch=destination, target_branch="main",
                                changed_files=[], tests=[], reviewer="pass", risk="low")
    assert bare(remote, "branch", "--list") == "* main"


def test_tampered_integration_branch_name_never_reaches_git(setup):
    service, _, remote, task_id, _ = setup
    service.tasks[task_id].integration["branch"] = "--force"
    with pytest.raises(TaskError, match="Invalid branch"):
        service.remote_preview(task_id, "push")
    service.tasks[task_id].integration["branch"] = "main"
    with pytest.raises(TaskError, match="not allowed"):
        service.remote_preview(task_id, "push")
    assert bare(remote, "branch", "--list") == "* main"


def test_remote_url_changed_after_preview_blocks_the_push(setup, tmp_path):
    service, _, remote, task_id, repo = setup
    preview = service.remote_preview(task_id, "push")["remote"]["push_preview"]
    other = tmp_path / "other.git"
    bare(remote.parent, "init", "-q", "--bare", str(other))
    git(repo, "remote", "set-url", "origin", str(other))
    with pytest.raises(TaskError):
        service.remote_approve(task_id, "push", fingerprint=preview["fingerprint"], confirmed=True)
    assert bare(other, "for-each-ref") == "" and bare(remote, "branch", "--list") == "* main"


def test_pr_text_injection_is_inert(setup):
    service, hub, _, task_id, _ = setup
    pushed(service, task_id)
    title = "Fix\n\n$(rm -rf /) `id` <script>alert(1)</script>"
    body = "x" * 30_000 + "\x00tail"
    preview = service.remote_preview(task_id, "pr", title=title, body=body)["remote"]["pr_preview"]
    assert "\n" not in preview["title"] and len(preview["body"]) == 20_000 and "\x00" not in preview["body"]
    service.remote_approve(task_id, "pr", fingerprint=preview["fingerprint"], confirmed=True)
    sent = hub.pulls[1]
    assert sent["title"] == preview["title"] and sent["body"] == preview["body"]
    assert sent["head"]["ref"] == preview["source_branch"] and sent["base"]["ref"] == "main"


def test_approval_from_an_unknown_source_is_refused(setup):
    service, _, remote, task_id, _ = setup
    preview = service.remote_preview(task_id, "push")["remote"]["push_preview"]
    for source in ("agent", "model", "github-actions", "auto"):
        with pytest.raises(TaskError, match="only from the desktop or a paired phone"):
            service.remote_approve(task_id, "push", fingerprint=preview["fingerprint"], confirmed=True, source=source)
    assert bare(remote, "branch", "--list") == "* main"
    assert "push" in service.get(task_id)["remote"]["pending"]  # a refused source does not consume it


def test_approval_from_another_task_is_refused(setup, git_repo, tmp_path):
    service, _, remote, task_id, _ = setup
    preview = service.remote_preview(task_id, "push")["remote"]["push_preview"]
    with pytest.raises(TaskError):
        service.remote_approve("f" * 32, "push", fingerprint=preview["fingerprint"], confirmed=True)
    assert bare(remote, "branch", "--list") == "* main"


def test_merge_preview_bound_to_its_pr_number(setup):
    service, hub, _, task_id, _ = setup
    pr_opened(service, task_id)
    preview = service.remote_preview(task_id, "merge")["remote"]["merge_preview"]
    hub.create_pull(OWNER, NAME, title="other", body="", head="main", base="main")
    service.tasks[task_id].remote["pr"]["number"] = 2
    with pytest.raises(TaskError):
        service.remote_approve(task_id, "merge", fingerprint=preview["fingerprint"], confirmed=True)
    assert not any(c.startswith("merge:") for c in hub.calls)


def test_concurrent_duplicate_approvals_execute_once(setup):
    service, hub, _remote, task_id, _ = setup
    pushed(service, task_id)
    preview = service.remote_preview(task_id, "pr")["remote"]["pr_preview"]
    results: list[str] = []

    def approve():
        try:
            service.remote_approve(task_id, "pr", fingerprint=preview["fingerprint"], confirmed=True)
            results.append("ok")
        except TaskError as exc:
            results.append(str(exc))

    threads = [threading.Thread(target=approve) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("ok") == 1 and hub.calls.count("create_pull") == 1 and len(hub.pulls) == 1


def test_nothing_remote_happens_without_a_user_action(setup):
    service, hub, remote, task_id, _ = setup
    service.get(task_id)
    service.list()
    assert hub.calls == [] and bare(remote, "branch", "--list") == "* main"
    view = service.get(task_id)
    assert view["remote"]["state"] == "not_checked" and not view["actions"]["push"]


def test_token_stays_in_the_authorization_header_only(monkeypatch):
    secret = "ghp_" + "S" * 36
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["auth"] = request.full_url, request.get_header("Authorization")
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {},
                                     io.BytesIO(json.dumps({"message": "Bad credentials"}).encode()))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(GitHubError) as caught:
        RestGitHub(token_provider=lambda: secret).repo("o", "r")
    assert seen["url"] == "https://api.github.com/repos/o/r" and seen["auth"] == f"Bearer {secret}"
    assert secret not in str(caught.value) and caught.value.status == 401


def test_audit_never_contains_credentials_or_urls_with_userinfo(setup):
    service, _, _, task_id, _ = setup
    pr_opened(service, task_id)
    stored = (service.audit_directory / f"{task_id}.json").read_text(encoding="utf-8")
    record = json.loads(stored)["remote"]
    assert [e["event"] for e in record["events"]][:3] == ["push_preview", "push_approved", "pushed"]
    assert "ghp_" not in stored and "Bearer" not in stored and "pending" not in record
