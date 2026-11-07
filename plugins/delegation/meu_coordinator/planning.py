"""Validate declared dependencies/write scopes before any helper starts.

These are planner contracts, not a filesystem sandbox. Workers receive their
scope through the parent's goal/context and retain the existing tool policy.
"""

from itertools import combinations
from pathlib import PurePosixPath
import unicodedata

from agent.delegation_provider import DelegationRouteError


def _path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DelegationRouteError("write_paths entries must be nonempty project-relative paths.")
    text = unicodedata.normalize("NFC", value.strip().replace("\\", "/"))
    path = PurePosixPath(text)
    if path.is_absolute() or ":" in text or ".." in path.parts or any(c in text for c in "*?[]\x00"):
        raise DelegationRouteError("Use literal project-relative write_paths without traversal or wildcards.")
    return str(path).casefold()


def _overlap(first: str, second: str) -> bool:
    return first == "." or second == "." or first == second or first.startswith(second + "/") or second.startswith(first + "/")


def validate_plan(tasks: list[dict]) -> None:
    scopes = []
    for index, task in enumerate(tasks):
        acceptance = task.get("acceptance")
        if not isinstance(acceptance, str) or not acceptance.strip():
            raise DelegationRouteError(f"Task {index}: supply concrete acceptance checks before delegating.")
        if type(task.get("parallel_safe")) is not bool:
            raise DelegationRouteError(f"Task {index}: explicitly set parallel_safe to true or false.")
        if task.get("tool_access", "inherit") not in ("inherit", "files_only"):
            raise DelegationRouteError(f"Task {index}: tool_access must be inherit or files_only.")
        if len(tasks) > 1 and not task["parallel_safe"]:
            raise DelegationRouteError(f"Task {index} depends on other work. Submit independent tasks now, "
                                       "wait for their results, then delegate the dependent task in a later call.")
        paths = task.get("write_paths")
        if not isinstance(paths, list):
            raise DelegationRouteError(f"Task {index}: supply write_paths ([] for read-only work).")
        if "review_of" in task:
            target = task["review_of"]
            dependencies = task.get("depends_on")
            stage = task.get("review_stage")
            valid_dependencies = dependencies == [target]
            if stage == "quality":
                valid_dependencies = (isinstance(dependencies, list) and len(dependencies) == 2
                                      and dependencies[0] == target)
            if not isinstance(target, str) or not valid_dependencies or paths:
                raise DelegationRouteError(f"Task {index}: a review must depend on its one deliverable and be read-only.")
        if task.get("images") and task.get("workload") != "vision":
            raise DelegationRouteError(f"Task {index}: use workload=vision for attached images.")
        scopes.append([_path(value) for value in paths])
    for (left, first), (right, second) in combinations(enumerate(scopes), 2):
        if any(_overlap(a, b) for a in first for b in second):
            raise DelegationRouteError(f"Tasks {left} and {right} have overlapping write_paths. "
                                       "Split their files or run them sequentially after reviewing each result.")
