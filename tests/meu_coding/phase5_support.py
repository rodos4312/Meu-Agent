"""Phase 5 helpers: a task service on a real temp repository, driven to a committed result."""

from __future__ import annotations

from meu_coding.task_service import CodingTaskService, ModelBundle
from tests.meu_coding.phase3_support import TASK, ScriptedModel, fake_adapter, fake_runner, git, good


def service_for(tmp_path, builders=(good,), runner=None) -> CodingTaskService:
    runner = runner or fake_runner()
    return CodingTaskService(
        models_factory=lambda: ModelBundle(None, ScriptedModel(list(builders)), None,
                                           {"architect": "fake:strong", "coder": "fake:strong",
                                            "reviewer": "fake:strong"}, "models_by_workload"),
        adapter_factory=lambda: fake_adapter(runner), spawn=lambda fn, name: fn(),
        audit_directory=tmp_path / "audit")


def configure_identity(repo) -> None:
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.invalid")


def start(service, repo) -> dict:
    return service.start(TASK.description, str(repo), TASK.explicit_files)


def approve(service, view, **overrides) -> dict:
    approval = view["approval"]
    return service.decide(view["task_id"], approval_id=approval["approval_id"], fingerprint=approval["fingerprint"],
                          approve=True, approver="tester", device="desktop", **overrides)


def committed(service, repo) -> dict:
    """start → approve → keep → commit on the worktree branch → READY_TO_INTEGRATE."""
    configure_identity(repo)
    view = approve(service, start(service, repo))
    service.keep(view["task_id"])
    plan = service.commit_prepare(view["task_id"])["commit"]
    return service.commit_confirm(view["task_id"], message="feat: add add()", token=plan["token"], confirmed=True)
