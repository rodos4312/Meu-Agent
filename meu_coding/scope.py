"""Path rules shared by the Architect, Reviewer and ImpactAnalyzer.

Pure string checks on repository-relative POSIX paths; nothing here touches the disk.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable

# Never proposed as edits by the Coding Engine, whatever the plan says. MEU's own write
# guards still apply at execution time; this is an earlier, independent refusal.
ALWAYS_PROTECTED = (".git/", ".hg/", ".svn/", ".env", ".env.", "node_modules/", ".venv/", "venv/")

_CONFIG_NAMES = frozenset({
    "pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "pytest.ini", "package.json",
    "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "uv.lock", "requirements.txt",
    "tsconfig.json", "dockerfile", "makefile", "config.yaml", ".gitignore",
})
_CONFIG_SUFFIXES = (".toml", ".ini", ".cfg", ".yaml", ".yml", ".json", ".env")
_SECURITY = re.compile(
    r"(?:^|[/_.-])(auth|oauth|security|secret|secrets|credential|credentials|token|tokens|"
    r"password|permission|permissions|approval|approvals|sandbox|guard|guards|crypto|"
    r"signing|keychain|session_secret)(?:[/_.-]|$)",
    re.IGNORECASE,
)
_CALLER = re.compile(
    r"(?:^|/)(web|ui|ui-tui|apps|frontend|desktop|api|routes|routers|web_routers|"
    r"handlers|views|controllers|endpoints|gateway)(?:/|$)|\.(tsx|jsx|vue|svelte)$",
    re.IGNORECASE,
)


def path_problem(path: str) -> str | None:
    """Why ``path`` cannot be an edit target, or None."""
    if not path or not path.strip():
        return "empty path"
    if path != path.strip():
        return f"{path!r} has surrounding whitespace"
    if "\\" in path:
        return f"{path!r} must use forward slashes"
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return f"{path!r} is absolute; edits must be repository-relative"
    if any(part == ".." for part in path.split("/")):
        return f"{path!r} leaves the repository ('..')"
    if posixpath.normpath(path) != path:
        return f"{path!r} is not a normalised path"
    return None


def _prefix_match(path: str, rule: str) -> bool:
    if rule.endswith("/"):
        return path.startswith(rule) or f"/{rule}" in f"/{path}"
    if rule.endswith("."):
        return posixpath.basename(path).startswith(rule)
    return path == rule or posixpath.basename(path) == rule


def is_protected(path: str, extra: Iterable[str] = ()) -> bool:
    return any(_prefix_match(path, rule) for rule in (*ALWAYS_PROTECTED, *extra))


def is_config_path(path: str) -> bool:
    name = posixpath.basename(path).lower()
    return name in _CONFIG_NAMES or name.endswith(_CONFIG_SUFFIXES)


def is_security_path(path: str) -> bool:
    return bool(_SECURITY.search(path))


def is_caller_path(path: str) -> bool:
    return bool(_CALLER.search(path))
