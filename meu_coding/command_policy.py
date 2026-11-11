"""Command policy for coding validation: logical checks → allowlisted argv, nothing else.

Models never supply commands. A ``CheckSpec`` (kind + targets) is turned into argv here,
from a fixed table, and only for targets that exist inside the workspace. Every argv is
then validated twice: by this module's own allowlist/denylist and by MEU's dangerous
command detector (``tools.approval_detection``). Argv is never joined into a shell string
for execution (no ``shell=True``); the joined form is only fed to the detector.

Allowed programs: the running Python (``-m pytest`` / ``-m py_compile`` only) and ruff
(``check`` only). Project commands (build, project-specific checks) run only when a trusted
caller registered that exact argv; a model cannot register one.
"""

from __future__ import annotations

import os
import posixpath
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from meu_coding.coding_interfaces import CheckKind, CheckSpec
from meu_coding.relevance import is_test_path
from meu_coding.schemas import safe_path_problem

BLOCKED_PROGRAMS = frozenset({
    "git", "rm", "del", "erase", "rmdir", "rd", "format", "diskpart", "reg", "regedit", "cmdkey",
    "powershell", "pwsh", "cmd", "bash", "sh", "zsh", "fish", "curl", "wget", "pip", "pip3", "uv", "uvx",
    "npm", "pnpm", "yarn", "npx", "sudo", "runas", "chmod", "chown", "mv", "move", "cp", "copy", "dd",
    "mkfs", "shutdown", "taskkill", "kill", "remove-item", "set-itemproperty", "new-itemproperty",
    "schtasks", "sc", "net", "netsh", "certutil", "bitsadmin", "security", "git-credential-manager",
})
BLOCKED_PATTERNS = (
    re.compile(r"\bgit\s+(reset|clean|checkout|switch|merge|rebase|push|commit|branch\s+-[dD]|worktree|"
               r"filter-branch|update-ref|gc|prune|stash|tag)\b", re.IGNORECASE),
    re.compile(r"--force\b|\s-f\s|--hard\b", re.IGNORECASE),
    re.compile(r"\brm\s+-[a-z]*r", re.IGNORECASE),
    re.compile(r"\bdel\s+/[sq]", re.IGNORECASE),
    re.compile(r"\bremove-item\b.*-recurse", re.IGNORECASE),
    re.compile(r"\b(format|diskpart|reg\s+(add|delete)|cmdkey|vssadmin)\b", re.IGNORECASE),
    re.compile(r"\b(pip|uv|npm|pnpm|yarn)\s+(install|add|remove|uninstall)\b", re.IGNORECASE),
)
_SHELL_META = re.compile(r"[;&|<>`$\n\r]")
PYTHON_MODULES = frozenset({"pytest", "py_compile"})


class CommandBlocked(Exception):
    pass


def _program_name(program: str) -> str:
    name = os.path.basename(program.replace("\\", "/")).lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1", ".com"):
        name = name.removesuffix(suffix)
    return name


def _default_detector(command: str) -> tuple[bool, str]:
    from tools.approval_detection import detect_dangerous_command

    dangerous, _key, description = detect_dangerous_command(command)
    return bool(dangerous), description or ""


def _default_ruff() -> str | None:
    from hermes_platform.resolver import locate_command

    resolution = locate_command("ruff")
    return resolution.command[0] if resolution.found else None


@dataclass(frozen=True)
class PlannedCommand:
    check: CheckSpec
    argv: tuple[str, ...]


@dataclass
class CommandPolicy:
    python: str = sys.executable
    project_commands: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    detector: Callable[[str], tuple[bool, str]] = _default_detector
    ruff_locator: Callable[[], str | None] = _default_ruff

    # ── validation ──────────────────────────────────────────────────────────

    def validate(self, argv: Sequence[str]) -> tuple[str, ...]:
        """Raise CommandBlocked unless ``argv`` is an allowed validation command."""
        argv = tuple(argv)
        if not argv or not all(isinstance(a, str) and a for a in argv):
            raise CommandBlocked("empty or non-string argument")
        if any("\x00" in a for a in argv):
            raise CommandBlocked("NUL byte in argument")
        joined = " ".join(argv)
        name = _program_name(argv[0])
        if name in BLOCKED_PROGRAMS:
            raise CommandBlocked(f"program {name!r} is never run by the Coding Engine")
        for pattern in BLOCKED_PATTERNS:
            if pattern.search(joined):
                raise CommandBlocked(f"blocked pattern in {joined!r}")
        if any(_SHELL_META.search(a) for a in argv):
            raise CommandBlocked("shell metacharacters are not allowed")
        self._check_allowlist(argv, name)
        dangerous, description = self.detector(joined)
        if dangerous:
            raise CommandBlocked(f"MEU approval detector flagged {joined!r}: {description}")
        return argv

    def _check_allowlist(self, argv: tuple[str, ...], name: str) -> None:
        if argv in self.project_commands.values():
            return
        if os.path.normcase(argv[0]) == os.path.normcase(self.python):
            if len(argv) < 3 or argv[1] != "-m" or argv[2] not in PYTHON_MODULES:
                raise CommandBlocked("python may only run '-m pytest' or '-m py_compile'")
            return
        if name == "ruff":
            if len(argv) < 2 or argv[1] != "check" or any(a in ("--fix", "--unsafe-fixes") for a in argv):
                raise CommandBlocked("ruff may only run 'check' without fixes")
            return
        raise CommandBlocked(f"program {argv[0]!r} is not on the validation allowlist")

    # ── planning ────────────────────────────────────────────────────────────

    def plan(self, check: CheckSpec, existing: Callable[[str], bool]) -> PlannedCommand | None:
        """argv for a logical check, or None when it does not apply (nothing to run).
        Raises CommandBlocked for a target that is unsafe or a command nobody registered."""
        for target in check.targets:
            problem = safe_path_problem(target)
            if problem:
                raise CommandBlocked(problem)
        targets = [t for t in check.targets if existing(t)]
        argv = self._argv(check, targets)
        return PlannedCommand(check, self.validate(argv)) if argv else None

    def _argv(self, check: CheckSpec, targets: list[str]) -> tuple[str, ...] | None:
        python_files = [t for t in targets if posixpath.splitext(t)[1] == ".py"]
        if check.kind == CheckKind.SYNTAX:
            return (self.python, "-m", "py_compile", *python_files) if python_files else None
        if check.kind == CheckKind.LINT:
            ruff = self.ruff_locator() if python_files else None
            return (ruff, "check", "--no-cache", *python_files) if ruff else None
        if check.kind == CheckKind.UNIT_TEST:
            tests = [t for t in python_files if is_test_path(t)]
            return (self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests) if tests else None
        registered = self.project_commands.get(check.kind.value)
        if check.command:
            if tuple(check.command) not in self.project_commands.values():
                raise CommandBlocked(f"unregistered project command {' '.join(check.command)!r}")
            return tuple(check.command)
        return registered
