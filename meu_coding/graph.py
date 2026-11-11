"""Incremental in-memory dependency graph over files, modules and symbols.

Node ids: a repository-relative file path, ``module:<name>`` for an import that does not
resolve to a file in the repository, and ``symbol:<path>:<qualified name>:<line>``.
Plain dicts and sets; no graph library is needed at this size.

``update_file`` / ``remove_file`` change one file without a rebuild. What a change can
affect, and is therefore recomputed:

* the file's own imports, definitions and references;
* imports of other files that could resolve differently now that a path or module name
  appeared or disappeared (tracked by the candidate keys each resolution tried);
* references of the files importing it (their scope includes its definitions).
"""

from __future__ import annotations

import posixpath
from collections import deque
from collections.abc import Iterable, Mapping

from meu_coding.interfaces import DependencyEdge, EdgeKind, ExtractionResult, RepositoryFile, Symbol

_JS_LANGUAGES = frozenset({"javascript", "typescript"})
_JS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".d.ts")
_SOURCE_ROOTS = ("src", "lib")


def symbol_id(symbol: Symbol) -> str:
    return f"symbol:{symbol.path}:{symbol.qualified_name}:{symbol.line}"


def normalize_path(target: str) -> str:
    path = target.replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return posixpath.normpath(path) if path else path


def _python_modules(path: str) -> list[str]:
    stem, ext = posixpath.splitext(path)
    if ext not in {".py", ".pyi"}:
        return []
    parts = stem.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return []
    names = [".".join(parts)]
    if len(parts) > 1 and parts[0] in _SOURCE_ROOTS:
        names.append(".".join(parts[1:]))
    return names


class RepositoryGraph:
    def __init__(self, files: Iterable[RepositoryFile] = (),
                 extractions: Mapping[str, ExtractionResult] | None = None) -> None:
        self.files: dict[str, RepositoryFile] = {}
        self.extractions: dict[str, ExtractionResult] = {}
        self._module_owners: dict[str, set[str]] = {}  # module name -> files claiming it
        self._imports: dict[str, set[str]] = {}
        self._reverse: dict[str, set[str]] = {}
        self._candidates: dict[str, set[str]] = {}  # resolution key -> files that tried it
        self._file_candidates: dict[str, set[str]] = {}
        self._definitions: dict[str, set[Symbol]] = {}
        self._references: dict[str, set[str]] = {}
        self._symbol_references: dict[str, set[tuple[str, str]]] = {}
        self._referencing_files: dict[str, set[str]] = {}
        extractions = extractions or {}
        files = list(files)
        for file in files:
            self._insert(file, extractions.get(file.path, ExtractionResult(file.path, (), "none")))
        for path in sorted(self.files):
            self._resolve_imports(path)
        for path in sorted(self.files):
            self._link_references(path)

    # ── incremental API ─────────────────────────────────────────────────────

    def update_file(self, file: RepositoryFile, extraction: ExtractionResult) -> None:
        path = file.path
        is_new = path not in self.files
        importers = set(self._reverse.get(path, ()))
        if not is_new:
            self._remove_definitions(path)
        self._insert(file, extraction)
        reresolve = {path} | (self._affected_by_keys(self._keys_for(path)) if is_new else set())
        for other in sorted(reresolve):
            self._clear_imports(other)
            self._resolve_imports(other)
        relink = reresolve | importers | set(self._reverse.get(path, ()))
        for other in sorted(relink & set(self.files)):
            self._unlink_references(other)
            self._link_references(other)

    def remove_file(self, path: str) -> None:
        if path not in self.files:
            return
        importers = set(self._reverse.get(path, ()))
        keys = self._keys_for(path)
        self._unlink_references(path)
        self._clear_imports(path)
        self._remove_definitions(path)
        for name in _python_modules(path):
            owners = self._module_owners.get(name, set())
            owners.discard(path)
            if not owners:
                self._module_owners.pop(name, None)
        del self.files[path]
        del self.extractions[path]
        self._reverse.pop(path, None)
        self._imports.pop(path, None)
        for other in sorted(self._affected_by_keys(keys) | importers):
            if other in self.files:
                self._clear_imports(other)
                self._resolve_imports(other)
                self._unlink_references(other)
                self._link_references(other)

    # ── internals ───────────────────────────────────────────────────────────

    def _insert(self, file: RepositoryFile, extraction: ExtractionResult) -> None:
        path = file.path
        self.files[path] = file
        self.extractions[path] = extraction
        self._imports.setdefault(path, set())
        self._reverse.setdefault(path, set())
        for name in _python_modules(path):
            self._module_owners.setdefault(name, set()).add(path)
        for symbol in extraction.definitions:
            self._definitions.setdefault(symbol.name, set()).add(symbol)
            if symbol.qualified_name != symbol.name:
                self._definitions.setdefault(symbol.qualified_name, set()).add(symbol)

    def _remove_definitions(self, path: str) -> None:
        for symbol in self.extractions[path].definitions:
            for key in {symbol.name, symbol.qualified_name}:
                bucket = self._definitions.get(key)
                if bucket is not None:
                    bucket.discard(symbol)
                    if not bucket:
                        del self._definitions[key]

    def _keys_for(self, path: str) -> set[str]:
        return {path, *_python_modules(path)}

    def _affected_by_keys(self, keys: set[str]) -> set[str]:
        return {f for key in keys for f in self._candidates.get(key, ())}

    def _module(self, name: str) -> str | None:
        owners = self._module_owners.get(name)
        return min(owners) if owners else None

    def _clear_imports(self, path: str) -> None:
        for target in self._imports.get(path, set()):
            if target in self._reverse:
                self._reverse[target].discard(path)
        self._imports[path] = set()
        for key in self._file_candidates.pop(path, set()):
            bucket = self._candidates.get(key)
            if bucket is not None:
                bucket.discard(path)
                if not bucket:
                    del self._candidates[key]

    def _resolve_imports(self, path: str) -> None:
        language = self.files[path].language
        tried: set[str] = set()
        for imp in self.extractions[path].imports:
            target = self._resolve_import(path, language, imp, tried)
            if target != path:
                self._imports[path].add(target)
                if target in self._reverse:
                    self._reverse[target].add(path)
        self._file_candidates[path] = tried
        for key in tried:
            self._candidates.setdefault(key, set()).add(path)

    def _link_references(self, path: str) -> None:
        extraction = self.extractions[path]
        scope = {path} | {t for t in self._imports[path] if t in self.files}
        local = {s.qualified_name: s for s in extraction.definitions}
        names = [(s.name, s.container) for s in extraction.references]
        names += [(s.container, None) for s in extraction.imports if s.container]
        targets: set[str] = set()
        pairs: set[tuple[str, str]] = set()
        for name, container in names:
            for definition in self._definitions.get(name, ()):
                if definition.path not in scope or definition.name != name:
                    continue
                target = symbol_id(definition)
                targets.add(target)
                owner = local.get(container) if container else None
                if owner is not None and owner != definition:
                    pairs.add((symbol_id(owner), target))
        self._references[path] = targets
        self._symbol_references[path] = pairs
        for target in targets:
            self._referencing_files.setdefault(target, set()).add(path)

    def _unlink_references(self, path: str) -> None:
        for target in self._references.pop(path, set()):
            bucket = self._referencing_files.get(target)
            if bucket is not None:
                bucket.discard(path)
                if not bucket:
                    del self._referencing_files[target]
        self._symbol_references.pop(path, None)

    def _resolve_import(self, path: str, language: str, imp: Symbol, tried: set[str]) -> str:
        if language == "python":
            resolved = self._resolve_python(path, imp.name, imp.container, tried)
        elif language in _JS_LANGUAGES:
            resolved = self._resolve_js(path, imp.name, tried)
        else:
            resolved = self._resolve_relative_file(path, imp.name, tried)
        return resolved or f"module:{imp.name}"

    def _resolve_python(self, path: str, name: str, imported: str | None, tried: set[str]) -> str | None:
        module = name
        if name.startswith("."):
            level = len(name) - len(name.lstrip("."))
            package = posixpath.dirname(path).split("/") if posixpath.dirname(path) else []
            if level - 1 > len(package):
                return None
            base = package[:len(package) - (level - 1)]
            rest = name[level:]
            module = ".".join(base + ([rest] if rest else []))
        candidates = [f"{module}.{imported}"] if imported and imported != "*" else []
        parts = module.split(".") if module else []
        candidates += [".".join(parts[:i]) for i in range(len(parts), 0, -1)]
        for candidate in candidates:
            tried.add(candidate)
            owner = self._module(candidate)
            if owner is not None:
                return owner
        return None

    def _first_file(self, candidates: list[str], tried: set[str]) -> str | None:
        for candidate in candidates:
            tried.add(candidate)
            if candidate in self.files:
                return candidate
        return None

    def _resolve_js(self, path: str, name: str, tried: set[str]) -> str | None:
        if not name.startswith("."):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(path), name))
        candidates = [base] + [base + s for s in _JS_SUFFIXES] + [f"{base}/index{s}" for s in _JS_SUFFIXES]
        if base.endswith(".js"):
            candidates += [base[:-3] + s for s in (".ts", ".tsx")]
        return self._first_file(candidates, tried)

    def _resolve_relative_file(self, path: str, name: str, tried: set[str]) -> str | None:
        local = posixpath.normpath(posixpath.join(posixpath.dirname(path), name))
        return self._first_file([local, normalize_path(name)], tried)

    # ── queries ─────────────────────────────────────────────────────────────

    def resolve_target(self, target: str) -> str:
        path = normalize_path(target)
        if path in self.files:
            return path
        return self._module(target) or path

    def get_dependencies(self, target: str, include_external: bool = False) -> tuple[str, ...]:
        deps = self._imports.get(self.resolve_target(target), set())
        return tuple(sorted(d for d in deps if include_external or not d.startswith("module:")))

    def get_reverse_dependencies(self, target: str) -> tuple[str, ...]:
        return tuple(sorted(self._reverse.get(self.resolve_target(target), set())))

    def lookup_symbol(self, name: str) -> tuple[Symbol, ...]:
        return tuple(sorted(self._definitions.get(name, ()), key=lambda s: (s.path, s.line, s.name, s.kind)))

    def defined_names(self) -> Iterable[str]:
        return self._definitions.keys()

    def symbols_for_file(self, target: str) -> tuple[Symbol, ...]:
        extraction = self.extractions.get(self.resolve_target(target))
        return extraction.definitions if extraction else ()

    def files_for_symbol(self, name: str) -> tuple[str, ...]:
        return tuple(sorted({s.path for s in self.lookup_symbol(name)}))

    def referencing_files(self, name: str) -> tuple[str, ...]:
        found = set()
        for symbol in self.lookup_symbol(name):
            found |= self._referencing_files.get(symbol_id(symbol), set())
        return tuple(sorted(found))

    def related_files(self, target: str, max_distance: int = 2) -> dict[str, int]:
        """Files within ``max_distance`` import hops in either direction, with the distance."""
        start = self.resolve_target(target)
        if start not in self.files:
            return {}
        distances, queue = {start: 0}, deque([start])
        while queue:
            current = queue.popleft()
            if distances[current] >= max_distance:
                continue
            neighbours = (self._imports.get(current, set()) | self._reverse.get(current, set()))
            for neighbour in sorted(neighbours):
                if neighbour in self.files and neighbour not in distances:
                    distances[neighbour] = distances[current] + 1
                    queue.append(neighbour)
        distances.pop(start)
        return dict(sorted(distances.items(), key=lambda kv: (kv[1], kv[0])))

    def edges(self) -> tuple[DependencyEdge, ...]:
        out: set[DependencyEdge] = set()
        for path, targets in self._imports.items():
            out.update(DependencyEdge(path, t, EdgeKind.IMPORTS) for t in targets)
        for path, extraction in self.extractions.items():
            for symbol in extraction.definitions:
                out.add(DependencyEdge(path, symbol_id(symbol), EdgeKind.DEFINES))
                out.add(DependencyEdge(symbol_id(symbol), path, EdgeKind.BELONGS_TO))
        for path, targets in self._references.items():
            out.update(DependencyEdge(path, t, EdgeKind.REFERENCES) for t in targets)
        for pairs in self._symbol_references.values():
            out.update(DependencyEdge(s, t, EdgeKind.REFERENCES) for s, t in pairs)
        return tuple(sorted(out, key=lambda e: (e.kind.value, e.source, e.target)))
