"""Path policy for a coordinator assignment on the local file tools."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat

from agent.file_safety import get_nt_namespace_error
from tools.path_security import has_unsafe_path_chars


def _literal_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip() or has_unsafe_path_chars(value):
        raise ValueError("Supply a literal file path.")
    if value.startswith(("//", "\\\\")) or get_nt_namespace_error(value):
        raise ValueError("Network and device paths are not permitted.")
    path = Path(value)
    if path.drive.startswith("\\\\"):
        raise ValueError("Network and device paths are not permitted.")
    if (path.anchor and not path.is_absolute()) or ".." in path.parts:
        raise ValueError("Use a project-relative or fully qualified path without traversal.")
    if any(":" in part or (os.name == "nt" and (part.endswith((".", " ")) or Path(part).is_reserved()))
           for part in path.parts if part != path.anchor):
        raise ValueError("Alternate file streams and ambiguous path components are not permitted.")
    return path


def _reject_links(path: Path) -> None:
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Symbolic links and Windows reparse points are not permitted.")


def local_project_root(value: str) -> Path:
    root = _literal_path(value)
    if not root.is_absolute():
        raise ValueError("Set root to the existing project's absolute directory.")
    _reject_links(root)
    if not root.is_dir():
        raise ValueError("The project's local directory is unavailable.")
    return root.resolve()


@dataclass(frozen=True)
class ProjectFileScope:
    root: Path
    write_paths: tuple[str, ...]

    def _target(self, raw: str, *, writing: bool = False) -> Path:
        candidate = self.root / _literal_path(raw)
        if not candidate.is_relative_to(self.root):
            raise ValueError("The path is outside the project directory.")
        _reject_links(candidate)
        path = candidate.resolve()
        if path.parts[:len(self.root.parts)] != self.root.parts:
            raise ValueError("The resolved path is outside the project directory.")
        if writing:
            if not any(self._permits_write(path, scope) for scope in self.write_paths):
                raise ValueError("The path is outside this assignment's write paths.")
            if path.exists() and path.is_file() and path.stat().st_nlink > 1:
                raise ValueError("Editing a file with multiple hard links is not permitted.")
        return path

    def _permits_write(self, path: Path, raw_scope: str) -> bool:
        scope = self.root / _literal_path(raw_scope.strip().replace("\\", "/"))
        if not path.is_relative_to(scope):
            return False
        _reject_links(scope)
        parts = scope.resolve().parts
        return path.parts[:len(parts)] == parts

    def prepare(self, name: str, args: dict) -> dict:
        """Validate the final arguments after middleware rewrites."""
        if name == "patch" and args.get("mode") == "patch":
            from tools.file_tools import _collect_v4a_header_paths
            from tools.patch_parser import parse_v4a_patch

            patch = args.get("patch")
            if not isinstance(patch, str):
                raise ValueError("Supply a text patch.")
            operations, error = parse_v4a_patch(patch)
            if error or not operations:
                raise ValueError(error or "Supply a patch with file operations.")
            headers = _collect_v4a_header_paths(patch)
            if isinstance(headers, str):
                raise ValueError("Supply literal patch header paths without traversal.")
            for header in headers[0]:
                self._target(header, writing=True)
            for operation in operations:
                self._target(operation.file_path, writing=True)
                if operation.new_path is not None:
                    self._target(operation.new_path, writing=True)
            if args.get("path"):
                self._target(args["path"], writing=True)
            return args

        raw = args.get("path")
        if name == "search_files" and (raw is None or isinstance(raw, str) and not raw.strip()):
            raw = "."
        target = self._target(raw, writing=name in {"write_file", "patch"})
        if name == "search_files":
            if not (target.is_dir() or target.is_file()):
                raise ValueError("Search requires one existing directory or file.")
            if str(args.get("pattern", "")).startswith("-"):
                raise ValueError("Search patterns must not start with a command option.")
        return {**args, "path": str(target)}
