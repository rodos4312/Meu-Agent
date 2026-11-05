"""Local project identity for curated memory, pinned when a session starts."""

from __future__ import annotations

import hashlib
import os
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from hermes_constants import get_hermes_home


def note_id(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ProjectMemoryScope:
    root: Path
    directory: Path

    @property
    def key(self) -> str:
        # Include the owning profile, not just the project, in approval replay identity.
        return str(self.directory)


def resolve_project_memory(cwd: str | None, *, home: Path | None = None) -> ProjectMemoryScope | None:
    """Only an explicitly selected existing workspace may acquire project memory.

    Registered folders share their primary folder's identity. Otherwise
    the nearest git root, or the selected folder itself, owns the notes. Never infer a
    project from the process cwd, which may be the application's installation directory.
    """
    if not cwd or not Path(cwd).is_absolute():
        return None
    root = Path(cwd).resolve()
    home = (home or get_hermes_home()).resolve()
    if not root.is_dir() or root in {Path(root.anchor), Path.home().resolve(), home}:
        return None

    # Read the existing project index without creating or migrating one during startup.
    registered = _registered_project(root, home)
    if registered:
        root = registered
    else:
        for candidate in (root, *root.parents):
            if (candidate / ".git").exists():
                root = candidate
                break
    identity = "folder:" + os.path.normcase(str(root))
    # A compact 96-bit key leaves room for atomic history filenames on Windows.
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return ProjectMemoryScope(root, home / "memories" / "projects" / digest)


def _registered_project(root: Path, home: Path) -> Path | None:
    import sqlite3

    database = home / "projects.db"
    if not database.is_file():
        return None
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.5)) as conn:
            rows = conn.execute(
                "SELECT p.primary_path, pf.path FROM project_folders pf "
                "JOIN projects p ON p.id = pf.project_id WHERE p.archived = 0"
            ).fetchall()
        owners = [(primary, Path(folder).resolve()) for primary, folder in rows
                  if Path(folder).is_absolute() and root.is_relative_to(Path(folder).resolve())]
        if owners:
            primary, folder = max(owners, key=lambda owner: len(owner[1].parts))
            # Keep existing folder notes when it is later registered as a project.
            return Path(primary).resolve() if primary and Path(primary).is_absolute() else folder
    except sqlite3.Error:
        # A missing/legacy/busy index must not prevent ordinary folder-based memory.
        return None
    return None
