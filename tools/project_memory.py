"""Local project identity for curated memory, pinned when a session starts."""

from __future__ import annotations

import hashlib
import logging
import os
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from hermes_constants import get_hermes_home


def note_id(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def anchor_project_memory(scope):
    from tools.project_memory_identity import identity_directory
    home = scope.directory.parent.parent.parent
    if not scope.root.is_dir():
        if (scope.directory / "PROJECT.md").is_file():
            return  # An existing conversation retains its pinned store after a folder move.
        raise ValueError("The selected project folder moved. Select its new location before saving the first note.")
    registered = _registered_project(scope.root, home)
    legacy = hashlib.sha256(("folder:" + os.path.normcase(str(scope.root))).encode()).hexdigest()[:24]
    directory = identity_directory(scope.root, home, legacy, registered[1] if registered else None, create=True)
    if directory != scope.directory:
        raise ValueError("Project memory identity changed. Reload project notes before saving; no notes were changed.")


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
        root, project = registered
    else:
        project = None
        for candidate in (root, *root.parents):
            if (candidate / ".git").exists():
                root = candidate
                break
    identity = "folder:" + os.path.normcase(str(root))
    # A compact 96-bit key leaves room for atomic history filenames on Windows.
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    from tools.project_memory_identity import identity_directory
    try:
        directory = identity_directory(root, home, digest, project)
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning("Project memory portability unavailable: %s", exc)
        directory = home / "memories/projects" / digest
    return ProjectMemoryScope(root, directory)


def _registered_project(root: Path, home: Path) -> tuple[Path, str] | None:
    import sqlite3

    database = home / "projects.db"
    if not database.is_file():
        return None
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.5)) as conn:
            rows = conn.execute(
                "SELECT p.primary_path, pf.path, p.id FROM project_folders pf "
                "JOIN projects p ON p.id = pf.project_id WHERE p.archived = 0"
            ).fetchall()
        owners = [(primary, Path(folder).resolve(), project) for primary, folder, project in rows
                  if Path(folder).is_absolute() and root.is_relative_to(Path(folder).resolve())]
        if owners:
            primary, folder, project = max(owners, key=lambda owner: len(owner[1].parts))
            # Keep existing folder notes when it is later registered as a project.
            return (Path(primary).resolve() if primary and Path(primary).is_absolute() else folder), project
    except sqlite3.Error:
        # A missing/legacy/busy index must not prevent ordinary folder-based memory.
        return None
    return None
