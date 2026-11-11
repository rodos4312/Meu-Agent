"""Coding Engine RPC surface (``coding.*``): thin handlers over ``meu_coding.task_service``.
Bodies are rebound onto server.py's globals at install (method_ctx.bind_module).

Every handler is profile-scoped, so the task service, its audit records, the provider routes
and credentials all belong to the profile the desktop addressed. Background work started by
the service inherits that scope (``spawn_context_thread`` copies the caller's context).
"""

from __future__ import annotations

import threading

from .method_ctx import HandlerRegistry, bind_module

_registry = HandlerRegistry()
method = _registry.method

# JSON-RPC error codes: refused by the task lifecycle (actionable message) / internal failure.
_E_CODING_REFUSED, _E_CODING_FAILED = 5072, 5073

_coding_services: dict[str, object] = {}
_coding_services_lock = threading.Lock()


def _coding_service():
    from hermes_constants import get_hermes_home

    from meu_coding.task_service import CodingTaskService

    key = str(get_hermes_home())
    with _coding_services_lock:
        service = _coding_services.get(key)
        if service is None:
            service = CodingTaskService()
            _coding_services[key] = service
        return service


def _coding_method(name: str):
    """Register a profile-scoped coding RPC that answers ``{"task": view}`` (or its own payload)."""
    def decorator(fn):
        @method(name)
        @_registry.profile_scoped
        def handler(rid, params: dict) -> dict:
            from meu_coding.task_service import TaskError

            try:
                return _ok(rid, fn(_coding_service(), params))
            except TaskError as exc:
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
                                   device=device)}


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


def register(server) -> None:
    bind_module(globals(), server)
