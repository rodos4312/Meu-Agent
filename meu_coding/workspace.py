"""Isolated workspaces and the bridge to MEU's existing file, patch, worktree and git helpers.

Every repository mutation the Coding Engine performs happens here, in a git worktree made by
``tools.subagent_worktree.create_subagent_worktree``, through MEU's V4A engine
(``tools.patch_parser``) and native atomic writer (``tools.file_operations_native``), with
MEU's write guards (``tools.file_tools_write_guards``) consulted for every target. Git is
only read here (``bounded_git_probe``, ``tools.working_diff``); creating and finalizing the
worktree is the existing worktree module's job, under its own safety rules.

Nothing here writes to the parent checkout. ``WorktreeFileOps`` confines every path to the
worktree root and refuses symlinked components, deletions and moves.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meu_coding.coding_interfaces import EditAction, EditOperation, EditStrategy

GIT_TIMEOUT = 20.0


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def _diff_path(header: str) -> str | None:
    path = header[4:].split("\t", 1)[0].strip()
    if path == "/dev/null":
        return None
    return path[2:] if path[:2] in ("a/", "b/") else path


def _file_header(old: str | None, new: str | None) -> tuple[str, str]:
    if new is None:
        return "delete", f"*** Delete File: {old}"
    if old is None:
        return "add", f"*** Add File: {new}"
    return "update", f"*** Update File: {new}"


def _hunk_line(mode: str | None, line: str) -> str | None:
    if mode == "update" and _HUNK.match(line):
        return "@@"
    if mode == "update" and line[:1] in ("+", "-", " "):
        return line
    if mode == "add" and line.startswith("+"):
        return line
    return None


def unified_to_v4a(diff: str) -> str:
    """Convert a unified diff into the V4A format MEU's ``patch`` tool applies.

    Hunk line numbers are dropped (V4A anchors on context), ``/dev/null`` sides become
    Add / Delete operations. Malformed input yields a patch MEU's parser will reject.
    """
    out = ["*** Begin Patch"]
    lines = diff.splitlines()
    mode: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            mode, header = _file_header(_diff_path(line), _diff_path(lines[i + 1]))
            out.append(header)
            i += 2
            continue
        converted = _hunk_line(mode, line)
        if converted is not None:
            out.append(converted)
        i += 1
    out.append("*** End Patch")
    return "\n".join(out) + "\n"



class WorkspaceError(Exception):
    pass


# ── read-only git facts ─────────────────────────────────────────────────────


def git_probe(root: str | Path, *args: str) -> str:
    from hermes_cli._subprocess_compat import bounded_git_probe

    return bounded_git_probe(["git", "-C", str(root), *args], timeout=GIT_TIMEOUT)


@dataclass(frozen=True)
class RepoIdentity:
    root: str
    branch: str
    head: str


def read_identity(path: str | Path) -> RepoIdentity:
    top = git_probe(path, "rev-parse", "--show-toplevel")
    if not top:
        raise WorkspaceError(f"{path} is not inside a git work tree")
    head = git_probe(top, "rev-parse", "HEAD")
    if not head:
        raise WorkspaceError("the repository has no commit to branch from")
    return RepoIdentity(os.path.normcase(str(Path(top).resolve())),
                        git_probe(top, "rev-parse", "--abbrev-ref", "HEAD"), head)


def decode_text(data: bytes) -> tuple[str, str | None, bool]:
    """``(LF-normalised text without BOM, on-disk line ending, had BOM)`` using MEU's own
    line-ending and BOM rules (``tools.file_operations_common``)."""
    from tools.file_operations_common import _detect_line_ending, _normalize_line_endings, _strip_bom

    text, had_bom = _strip_bom(data.decode("utf-8"))
    return _normalize_line_endings(text, "\n"), _detect_line_ending(text), had_bom


def file_sha256(path: Path) -> str | None:
    """Identity of a file's TEXT (UTF-8, BOM and line endings normalised), ``None`` when
    absent. A checkout's CRLF conversion is not a content change; any other byte is."""
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise WorkspaceError(f"{path.name} is not a regular file")
    try:
        text = decode_text(path.read_bytes())[0]
    except (OSError, UnicodeDecodeError) as exc:
        raise WorkspaceError(f"cannot read {path.name} as UTF-8 text: {type(exc).__name__}") from None
    return text_sha256(text)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# ── edits → MEU patch engine input ──────────────────────────────────────────


def _hunk_lines(prefix: str, text: str) -> list[str]:
    return [prefix + line for line in text.splitlines()]


def to_v4a(op: EditOperation) -> str | None:
    """V4A text for one edit, or None for a whole-file update (written directly)."""
    if op.strategy == EditStrategy.V4A_PATCH:
        return op.patch or ""
    if op.strategy == EditStrategy.UNIFIED_DIFF:
        return unified_to_v4a(op.patch or "")
    if op.strategy == EditStrategy.SEARCH_REPLACE:
        body = ["@@", *_hunk_lines("-", op.search or ""), *_hunk_lines("+", op.replace or "")]
        return "\n".join(["*** Begin Patch", f"*** Update File: {op.path}", *body, "*** End Patch", ""])
    if op.action == EditAction.CREATE:
        lines = (op.content or "").splitlines() or [""]
        return "\n".join(["*** Begin Patch", f"*** Add File: {op.path}", *("+" + line for line in lines),
                          "*** End Patch", ""])
    return None


_PATCH_BODY = re.compile(r"^\*\*\*\s*Begin\s+Patch\s*$\n?(.*?)^\*\*\*\s*End\s+Patch\s*$", re.DOTALL | re.MULTILINE)


def combined_patch(operations: Iterable[EditOperation]) -> str:
    bodies = []
    for op in operations:
        text = to_v4a(op)
        if text is None:
            continue
        match = _PATCH_BODY.search(text)
        bodies.append((match.group(1) if match else text).rstrip("\n"))
    return "*** Begin Patch\n" + "\n".join(bodies) + "\n*** End Patch\n" if bodies else ""


# ── file operations for MEU's V4A applier ───────────────────────────────────


class _FileOpsBase:
    """The four methods ``tools.patch_parser.apply_v4a_operations`` uses. Deletes and moves
    are refused: the Coding Engine never removes or renames files."""

    def delete_file(self, path: str):
        from tools.file_operations_common import WriteResult

        return WriteResult(error=f"deleting {path} is not allowed for the Coding Engine")

    def move_file(self, src: str, dst: str):
        from tools.file_operations_common import WriteResult

        return WriteResult(error=f"moving {src} is not allowed for the Coding Engine")


@dataclass
class MemoryFileOps(_FileOpsBase):
    """In-memory files: ``None`` = absent. Used to preview the exact result of a proposal."""

    files: dict[str, str | None]
    written: dict[str, str] = field(default_factory=dict)

    def read_file_raw(self, path: str):
        from tools.file_operations_common import ReadResult

        if path in self.written:
            return ReadResult(content=self.written[path])
        content = self.files.get(path)
        if content is None:
            return ReadResult(error=f"File not found: {path}", not_found=True)
        return ReadResult(content=content)

    def write_file(self, path: str, content: str):
        from tools.file_operations_common import WriteResult

        self.written[path] = content
        return WriteResult(bytes_written=len(content.encode("utf-8")))


class WorktreeFileOps(_FileOpsBase):
    """Reads and atomic writes confined to ``root``; MEU's write guards checked per write."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.written: dict[str, str] = {}

    def confine(self, rel: str) -> Path:
        from meu_coding.schemas import safe_path_problem

        problem = safe_path_problem(rel)
        if problem:
            raise WorkspaceError(problem)
        current = self.root
        for part in rel.split("/"):
            current = current / part
            if current.is_symlink():
                raise WorkspaceError(f"{rel} passes through a symbolic link")
        if not current.resolve().is_relative_to(self.root):
            raise WorkspaceError(f"{rel} resolves outside the workspace")
        return current

    def read_file_raw(self, path: str):
        from tools.file_operations_common import ReadResult

        target = self.confine(path)
        if not target.exists():
            return ReadResult(error=f"File not found: {path}", not_found=True)
        try:
            return ReadResult(content=decode_text(target.read_bytes())[0])
        except (OSError, UnicodeDecodeError) as exc:
            return ReadResult(error=f"cannot read {path}: {type(exc).__name__}")

    def write_file(self, path: str, content: str):
        from tools.file_operations_common import _UTF8_BOM, WriteResult, _normalize_line_endings
        from tools.file_operations_native import atomic_write
        from tools.file_tools_write_guards import _check_sensitive_path, _is_internal_file_tool_content

        target = self.confine(path)
        refusal = _check_sensitive_path(str(target)) or (
            "refusing to write internal tool display text" if _is_internal_file_tool_content(content) else None)
        if refusal:
            return WriteResult(error=refusal)
        ending, bom = None, False
        if target.exists():  # keep the file's own line endings and BOM, as MEU's write_file does
            _text, ending, bom = decode_text(target.read_bytes())
        data = _normalize_line_endings(content, ending) if ending else content
        error = atomic_write(str(target), ((_UTF8_BOM if bom else "") + data).encode("utf-8"))
        if error:
            return WriteResult(error=error)
        self.written[path] = content
        return WriteResult(bytes_written=len(content.encode("utf-8")))


def apply_operations(operations: tuple[EditOperation, ...], file_ops: Any) -> tuple[bool, str]:
    """Apply through MEU's V4A engine (validate-all-then-write), then whole-file updates."""
    from tools.patch_parser import apply_v4a_operations, parse_v4a_patch

    patch = combined_patch(operations)
    if patch:
        parsed, error = parse_v4a_patch(patch)
        if error:
            return False, error
        result = apply_v4a_operations(parsed, file_ops)
        if not result.success:
            return False, result.error or "patch failed"
    for op in operations:
        if op.strategy == EditStrategy.WHOLE_FILE and op.action == EditAction.UPDATE:
            current = file_ops.read_file_raw(op.path)
            if current.error:
                return False, f"cannot rewrite {op.path}: {current.error}"
            written = file_ops.write_file(op.path, op.content or "")
            if written.error:
                return False, written.error
    return True, ""


# ── the isolated worktree ───────────────────────────────────────────────────


@dataclass
class Worktree:
    path: Path
    branch: str
    base_commit: str
    repo_root: str
    info: dict[str, str]
    touched: bool = False  # an apply was attempted: never discard automatically
    finalized: dict[str, Any] | None = None


class MeuWorktreeWorkspace:
    """An isolated workspace over ``tools/subagent_worktree.py`` (create, inspect, finalize)."""

    def open(self, repo_root: str, task_id: str | None = None) -> Worktree:
        from tools.subagent_worktree import create_subagent_worktree

        name = f"coding-{task_id or uuid.uuid4().hex[:10]}"
        info = create_subagent_worktree(repo_root, name)
        if not info:
            raise WorkspaceError("the existing worktree system could not create an isolated worktree")
        return Worktree(Path(info["path"]), info["branch"], info.get("base_commit", ""),
                        info.get("repo_root", repo_root), info)

    def diff(self, worktree: Worktree) -> dict[str, Any]:
        from tools.working_diff import collect_working_diff

        result = collect_working_diff(str(worktree.path), mode="all")
        if not result.get("success"):
            raise WorkspaceError(f"could not read the worktree diff: {result.get('error')}")
        return result

    def commits_since_base(self, worktree: Worktree) -> int | None:
        out = git_probe(worktree.path, "rev-list", "--count", f"{worktree.base_commit}..HEAD")
        return int(out) if out.isdigit() else None

    def finalize(self, worktree: Worktree, *, discard: bool) -> dict[str, Any]:
        """Existing rules decide: ``discard`` prunes a clean tree and archives (then removes) a
        dirty one; without ``discard`` the tree is always kept for inspection."""
        from tools.subagent_worktree import finalize_subagent_worktree

        worktree.finalized = finalize_subagent_worktree(worktree.info, prune=discard)
        return worktree.finalized


_DIFF_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)


def changed_files(diff: dict[str, Any]) -> tuple[str, ...]:
    paths = [m.group(2) for m in _DIFF_HEADER.finditer(diff.get("diff", ""))]
    paths += list(diff.get("untracked", []))
    return tuple(sorted(dict.fromkeys(p.strip() for p in paths)))


def diff_counts(diff_text: str) -> tuple[int, int]:
    additions = deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return additions, deletions
