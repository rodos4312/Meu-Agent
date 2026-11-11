"""Deterministic, read-only enumeration of a repository's source files.

Files are only ever opened for reading (``rb``); nothing is executed. Symlinks are skipped
so a link cannot pull files from outside the explicit root into the index.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from meu_coding.interfaces import RepositoryFile

DEFAULT_IGNORED_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "dist", "build", "__pycache__", ".venv", "venv",
    "env", "coverage", "htmlcov", ".coverage", ".cache", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".nox", ".idea", ".vscode", ".vs", ".next", ".nuxt", ".turbo",
    ".parcel-cache", ".gradle", "target", ".eggs", ".ipynb_checkpoints",
})

LANGUAGES = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".mts": "typescript", ".cts": "typescript", ".go": "go", ".rs": "rust", ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin", ".cs": "csharp", ".c": "c", ".h": "c", ".cc": "cpp",
    ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".rb": "ruby", ".php": "php",
    ".swift": "swift", ".scala": "scala", ".lua": "lua", ".sh": "shell", ".bash": "shell",
    ".ps1": "powershell", ".psm1": "powershell", ".mq5": "mql", ".mqh": "mql", ".sql": "sql",
    ".md": "markdown", ".rst": "rst", ".txt": "text", ".toml": "toml", ".yaml": "yaml",
    ".yml": "yaml", ".json": "json", ".ini": "ini", ".cfg": "ini", ".html": "html",
    ".css": "css", ".scss": "css", ".vue": "vue", ".svelte": "svelte",
}

BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip", ".gz", ".tgz",
    ".bz2", ".xz", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo", ".class",
    ".jar", ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".wav", ".ogg", ".mov",
    ".sqlite", ".db", ".bin", ".ex5", ".lockb",
})

_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class IndexConfig:
    include: tuple[str, ...] = ()
    """Glob patterns on the relative path; when given, only matching files are indexed."""
    exclude: tuple[str, ...] = ()
    ignored_dirs: frozenset[str] = field(default=DEFAULT_IGNORED_DIRS)
    respect_gitignore: bool = True
    max_file_bytes: int = 1_000_000


def language_for(path: str) -> str:
    return LANGUAGES.get(os.path.splitext(path)[1].lower(), "unknown")


def is_binary(abs_path: str) -> bool:
    if os.path.splitext(abs_path)[1].lower() in BINARY_EXTENSIONS:
        return True
    with open(abs_path, "rb") as handle:
        return b"\0" in handle.read(_SNIFF_BYTES)


def read_source(root: str | Path, rel_path: str) -> str:
    with open(Path(root) / rel_path, "rb") as handle:
        return handle.read().decode("utf-8", errors="replace")


@dataclass(frozen=True)
class _IgnoreRule:
    regex: re.Pattern[str]
    negated: bool
    dir_only: bool


def _glob_to_regex(pattern: str) -> str:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                out.append(pattern[i:end + 1].replace("[!", "[^"))
                i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


def parse_gitignore(text: str) -> tuple[_IgnoreRule, ...]:
    """The common subset of gitignore syntax: comments, ``!`` negation, trailing ``/``
    (directories only), leading or inner ``/`` (anchored) and ``*``/``**``/``?``/``[]``."""
    rules = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        line = line[1:] if negated else line
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if not line:
            continue
        anchored = "/" in line
        body = _glob_to_regex(line.lstrip("/"))
        prefix = "" if anchored else "(?:.*/)?"
        rules.append(_IgnoreRule(re.compile(f"^{prefix}{body}$"), negated, dir_only))
    return tuple(rules)


def _gitignored(rules: list[tuple[str, tuple[_IgnoreRule, ...]]], rel: str, is_dir: bool) -> bool:
    ignored = False
    for base, base_rules in rules:
        if base and not rel.startswith(base + "/"):
            continue
        local = rel[len(base) + 1:] if base else rel
        for rule in base_rules:
            if rule.dir_only and not is_dir:
                continue
            if rule.regex.match(local):
                ignored = not rule.negated
    return ignored


class RepositoryIndexer:
    def __init__(self, root: str | Path, config: IndexConfig | None = None) -> None:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise NotADirectoryError(f"repository root is not a directory: {root}")
        self.root = resolved
        self.config = config or IndexConfig()

    def scan(self, known: Mapping[str, RepositoryFile] | None = None) -> tuple[RepositoryFile, ...]:
        """All indexable files. A file in ``known`` with the same size and mtime reuses that
        record, skipping the binary sniff (one open per file is most of a rescan's cost)."""
        found: list[RepositoryFile] = []
        self._walk("", [], found, known or {})
        return tuple(sorted(found, key=lambda f: f.path))

    def file_record(self, rel: str, known: Mapping[str, RepositoryFile] | None = None) -> RepositoryFile | None:
        """The record for one path, or ``None`` if it is missing or not indexable, applying
        the same directory, ``.gitignore`` and include/exclude rules as ``scan``."""
        parts = rel.split("/")
        rules: list = []
        rel_dir = ""
        for name in ["", *parts[:-1]]:
            rel_dir = f"{rel_dir}/{name}".strip("/") if name else rel_dir
            if name and not self._dir_allowed(name, rel_dir, rules):
                return None
            rules = rules + self._dir_rules(self.root / rel_dir if rel_dir else self.root, rel_dir)
        abs_path = self.root / rel
        try:
            if abs_path.is_symlink() or not abs_path.is_file():
                return None
            stat = abs_path.stat()
        except OSError:
            return None
        return self._record(rel, str(abs_path), stat, rules, known or {})

    def _walk(self, rel_dir: str, rules: list, found: list[RepositoryFile],
              known: Mapping[str, RepositoryFile]) -> None:
        abs_dir = self.root / rel_dir if rel_dir else self.root
        rules = rules + self._dir_rules(abs_dir, rel_dir)
        try:
            entries = sorted(os.scandir(abs_dir), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if self._dir_allowed(entry.name, rel, rules):
                    self._walk(rel, rules, found, known)
            elif entry.is_file():
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                record = self._record(rel, entry.path, stat, rules, known)
                if record is not None:
                    found.append(record)

    def _dir_rules(self, abs_dir: Path, rel_dir: str) -> list:
        if not self.config.respect_gitignore:
            return []
        gitignore = abs_dir / ".gitignore"
        try:
            text = gitignore.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [(rel_dir, parse_gitignore(text))]

    def _dir_allowed(self, name: str, rel: str, rules: list) -> bool:
        if name in self.config.ignored_dirs or name.endswith(".egg-info"):
            return False
        if self._excluded(rel + "/"):
            return False
        return not _gitignored(rules, rel, is_dir=True)

    def _excluded(self, rel: str) -> bool:
        return any(fnmatch.fnmatchcase(rel, pattern) for pattern in self.config.exclude)

    def _record(self, rel: str, abs_path: str, stat: os.stat_result, rules: list,
                known: Mapping[str, RepositoryFile]) -> RepositoryFile | None:
        if self._excluded(rel) or _gitignored(rules, rel, is_dir=False):
            return None
        if self.config.include and not any(fnmatch.fnmatchcase(rel, p) for p in self.config.include):
            return None
        previous = known.get(rel)
        if previous is not None and (previous.size, previous.mtime_ns) == (stat.st_size, stat.st_mtime_ns):
            return previous
        try:
            if stat.st_size > self.config.max_file_bytes or is_binary(abs_path):
                return None
        except OSError:
            return None
        extension = os.path.splitext(rel)[1].lower()
        return RepositoryFile(rel, language_for(rel), extension, stat.st_size, stat.st_mtime_ns)
