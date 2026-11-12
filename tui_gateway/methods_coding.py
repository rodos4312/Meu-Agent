"""Coding Engine RPC surface (``coding.*``): thin handlers over ``meu_coding.task_service``.
Bodies are rebound onto server.py's globals at install (method_ctx.bind_module).

Every handler is profile-scoped, so the task service, its audit records, the provider routes
and credentials all belong to the profile the desktop addressed. Background work started by
the service inherits that scope (``spawn_context_thread`` copies the caller's context).
"""

from __future__ import annotations

from .method_ctx import HandlerRegistry, bind_module

_registry = HandlerRegistry()
method = _registry.method

# JSON-RPC error codes: refused by the task lifecycle (actionable message) / internal failure.
_E_CODING_REFUSED, _E_CODING_FAILED = 5072, 5073

def _coding_service():
    from meu_coding.service_registry import current_service

    return current_service()


def _coding_method(name: str):
    """Register a profile-scoped coding RPC that answers ``{"task": view}`` (or its own payload)."""
    def decorator(fn):
        @method(name)
        @_registry.profile_scoped
        def handler(rid, params: dict) -> dict:
            from meu_coding.autonomous_planner import PlannerError
            from meu_coding.task_service import TaskError

            try:
                return _ok(rid, fn(_coding_service(), params))
            except (TaskError, PlannerError) as exc:
                return _err(rid, _E_CODING_REFUSED, str(exc))
            except Exception as exc:
                logger.warning("coding RPC %s failed", name, exc_info=True)
                return _err(rid, _E_CODING_FAILED, f"{type(exc).__name__}: {exc}")
        return handler
    return decorator


@_coding_method("coding.start")
def _coding_start(service, params: dict) -> dict:
    return {"task": service.start(str(params["description"]), str(params["project_root"]),
                                  tuple(params.get("explicit_files") or ()),
                                  tuple(params.get("protected_paths") or ()))}


@_coding_method("coding.get")
def _coding_get(service, params: dict) -> dict:
    return {"task": service.get(str(params["task_id"]))}


@_coding_method("coding.list")
def _coding_list(service, params: dict) -> dict:
    return {"tasks": service.list()}


@_coding_method("coding.decide")
def _coding_decide(service, params: dict) -> dict:
    device = str(params.get("device") or "desktop")
    return {"task": service.decide(str(params["task_id"]), approval_id=str(params["approval_id"]),
                                   fingerprint=str(params["fingerprint"]),
                                   approve=params["decision"] == "approve", approver=f"user@{device}",
                                   device=device, source="desktop")}


@_coding_method("coding.keep")
def _coding_keep(service, params: dict) -> dict:
    return {"task": service.keep(str(params["task_id"]))}


@_coding_method("coding.reject")
def _coding_reject(service, params: dict) -> dict:
    return {"task": service.reject(str(params["task_id"]))}


@_coding_method("coding.repair")
def _coding_repair(service, params: dict) -> dict:
    return {"task": service.repair(str(params["task_id"]))}


@_coding_method("coding.commit.prepare")
def _coding_commit_prepare(service, params: dict) -> dict:
    return {"task": service.commit_prepare(str(params["task_id"]))}


@_coding_method("coding.commit.confirm")
def _coding_commit_confirm(service, params: dict) -> dict:
    return {"task": service.commit_confirm(str(params["task_id"]), message=str(params["message"]),
                                           token=str(params["token"]), confirmed=params["confirmed"] is True)}


@_coding_method("coding.integration.preview")
def _coding_integration_preview(service, params: dict) -> dict:
    return {"task": service.integration_preview(str(params["task_id"]))}


@_coding_method("coding.integration.approve")
def _coding_integration_approve(service, params: dict) -> dict:
    return {"task": service.integration_approve(str(params["task_id"]), token=str(params["token"]),
                                                confirmed=params["confirmed"] is True, source="desktop")}


@_coding_method("coding.integration.cancel")
def _coding_integration_cancel(service, params: dict) -> dict:
    return {"task": service.integration_cancel(str(params["task_id"]), source="desktop")}


@_coding_method("coding.pr.prepare")
def _coding_pr_prepare(service, params: dict) -> dict:
    return {"task": service.pr_prepare(str(params["task_id"]))}


@_coding_method("coding.pr.update")
def _coding_pr_update(service, params: dict) -> dict:
    return {"task": service.pr_update(str(params["task_id"]), title=params.get("title"), body=params.get("body"),
                                      status=params.get("status"))}


def _remote_kind(params: dict) -> str:
    kind = str(params["kind"])
    if kind not in ("push", "pr", "merge"):
        raise ValueError("unknown remote action")
    return kind


@_coding_method("coding.remote.detect")
def _coding_remote_detect(service, params: dict) -> dict:
    return {"task": service.remote_detect(str(params["task_id"]))}


@_coding_method("coding.remote.preview")
def _coding_remote_preview(service, params: dict) -> dict:
    return {"task": service.remote_preview(str(params["task_id"]), _remote_kind(params), title=params.get("title"),
                                           body=params.get("body"), method=str(params.get("method") or "squash"))}


@_coding_method("coding.remote.approve")
def _coding_remote_approve(service, params: dict) -> dict:
    return {"task": service.remote_approve(str(params["task_id"]), _remote_kind(params),
                                           fingerprint=str(params["fingerprint"]),
                                           confirmed=params["confirmed"] is True, source="desktop")}


@_coding_method("coding.remote.cancel")
def _coding_remote_cancel(service, params: dict) -> dict:
    return {"task": service.remote_cancel(str(params["task_id"]), _remote_kind(params), source="desktop")}


@_coding_method("coding.remote.refresh")
def _coding_remote_refresh(service, params: dict) -> dict:
    return {"task": service.remote_refresh(str(params["task_id"]))}


@_coding_method("coding.remote.feedback")
def _coding_remote_feedback(service, params: dict) -> dict:
    return {"comments": service.remote_feedback(str(params["task_id"]))}


@_coding_method("coding.remote.repair")
def _coding_remote_repair(service, params: dict) -> dict:
    return {"task": service.remote_repair_task(str(params["task_id"]), [int(i) for i in params["comment_ids"]])}


@_coding_method("coding.memory.candidates")
def _coding_memory_candidates(service, params: dict) -> dict:
    return {"candidates": service.memory_candidates(str(params["task_id"]))}


@_coding_method("coding.memory.decide")
def _coding_memory_decide(service, params: dict) -> dict:
    return {"task": service.memory_decide(str(params["task_id"]), str(params["candidate_id"]),
                                          accept=params["decision"] == "accept", source="desktop")}


@_coding_method("coding.semantic.status")
def _coding_semantic_status(service, params: dict) -> dict:
    return {"semantic": service.semantic_status(str(params["project_root"]))}


@_coding_method("coding.roadmap.create")
def _coding_roadmap_create(service, params: dict) -> dict:
    return {"roadmap": service.roadmap_create(str(params["goal"]), str(params["project_root"]))}


@_coding_method("coding.roadmap.get")
def _coding_roadmap_get(service, params: dict) -> dict:
    return {"roadmap": service.roadmap_get(str(params["roadmap_id"]))}


@_coding_method("coding.roadmap.list")
def _coding_roadmap_list(service, params: dict) -> dict:
    return {"roadmaps": service.roadmap_list()}


@_coding_method("coding.roadmap.approve")
def _coding_roadmap_approve(service, params: dict) -> dict:
    return {"roadmap": service.milestone_approve(str(params["roadmap_id"]), str(params["milestone_id"]),
                                                 fingerprint=str(params["fingerprint"]),
                                                 revision=int(params["revision"]),
                                                 confirmed=params["confirmed"] is True, source="desktop")}


@_coding_method("coding.roadmap.reject")
def _coding_roadmap_reject(service, params: dict) -> dict:
    return {"roadmap": service.milestone_reject(str(params["roadmap_id"]), str(params["milestone_id"]),
                                                source="desktop")}


@_coding_method("coding.roadmap.edit")
def _coding_roadmap_edit(service, params: dict) -> dict:
    return {"roadmap": service.roadmap_edit(str(params["roadmap_id"]), list(params["milestones"]),
                                            revision=int(params["revision"]), source="desktop")}


@_coding_method("coding.roadmap.revision")
def _coding_roadmap_revision(service, params: dict) -> dict:
    return {"roadmap": service.roadmap_revision_decide(str(params["roadmap_id"]), str(params["revision_id"]),
                                                       accept=params["decision"] == "accept", source="desktop")}


@_coding_method("coding.roadmap.pause")
def _coding_roadmap_pause(service, params: dict) -> dict:
    return {"roadmap": service.roadmap_pause(str(params["roadmap_id"]), params["paused"] is True, source="desktop")}


@_coding_method("coding.roadmap.replan")
def _coding_roadmap_replan(service, params: dict) -> dict:
    return {"roadmap": service.roadmap_replan(str(params["roadmap_id"]))}


def register(server) -> None:
    bind_module(globals(), server)
