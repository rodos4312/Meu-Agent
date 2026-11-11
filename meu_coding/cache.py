"""Extraction cache keyed by path + mtime + size (+ optional content hash).

An entry is reused only while the file's metadata (and, with ``verify_content``, its
SHA-256) still matches, so a changed source file is always re-extracted. A broken or
unwritable cache degrades to a miss; it never breaks analysis.

``JsonFileCache`` is compact on disk: per file one row of plain JSON with a local string
table and a flat integer list per symbol (path and language are implied by the entry, names
are stored once per file, no source text, no field names). Entries are spread over a fixed
number of shard files, so saving after a small change rewrites only the touched shards, and
loaded rows are decoded into ``Symbol`` objects only when a file is actually asked for.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import zlib
from pathlib import Path

from meu_coding.interfaces import DEEP, ExtractionResult, RepositoryFile, Symbol

logger = logging.getLogger(__name__)

_FORMAT_VERSION = 2
_KINDS = ("class", "function", "method", "variable", "import", "reference")
_KIND_CODES = {kind: code for code, kind in enumerate(_KINDS)}
_FIELDS = 6  # kind, name, line, column, container, end_line (-1 = None)


def content_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MemoryCache:
    def __init__(self, verify_content: bool = False) -> None:
        self.verify_content = verify_content
        self._entries: dict[str, tuple[int, int, str | None, ExtractionResult]] = {}

    def _matches(self, file: RepositoryFile, size: int, mtime_ns: int, cached: str | None,
                 digest: str | None) -> bool:
        if (size, mtime_ns) != (file.size, file.mtime_ns):
            return False
        return not self.verify_content or cached == digest

    def get(self, file: RepositoryFile, digest: str | None = None) -> ExtractionResult | None:
        entry = self._entries.get(file.path)
        if entry is None or not self._matches(file, entry[0], entry[1], entry[2], digest):
            return None
        return entry[3]

    def put(self, file: RepositoryFile, result: ExtractionResult, digest: str | None = None) -> None:
        self._entries[file.path] = (file.size, file.mtime_ns, digest, result)

    def prune(self, live_paths: set[str]) -> None:
        for path in set(self._entries) - live_paths:
            del self._entries[path]

    def known_files(self) -> dict[str, tuple[int, int]]:
        """``{path: (size, mtime_ns)}`` of every cached file, so a rescan can skip sniffing them."""
        return {path: (entry[0], entry[1]) for path, entry in self._entries.items()}

    def save(self) -> None:
        """In-memory caches have nothing to persist."""


class JsonFileCache(MemoryCache):
    """``MemoryCache`` persisted under one directory the caller names."""

    def __init__(self, directory: str | Path, verify_content: bool = False, shards: int = 64) -> None:
        super().__init__(verify_content)
        self.directory = Path(directory)
        self.shards = shards
        self._raw: dict[str, list] = {}
        self._dirty: set[int] = set()
        self._load()

    def _shard(self, path: str) -> int:
        return zlib.crc32(path.encode("utf-8")) % self.shards

    def _shard_file(self, shard: int) -> Path:
        return self.directory / f"symbols-{shard:03d}.json"

    def _load(self) -> None:
        for shard in range(self.shards):
            target = self._shard_file(shard)
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                if raw.get("version") == _FORMAT_VERSION and raw.get("shards") == self.shards:
                    self._raw.update(raw["entries"])
            except FileNotFoundError:
                continue
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                logger.warning("ignoring unreadable meu_coding cache shard %s: %s", target, exc)

    def get(self, file: RepositoryFile, digest: str | None = None) -> ExtractionResult | None:
        hit = super().get(file, digest)
        if hit is not None:
            return hit
        row = self._raw.get(file.path)
        if row is None:
            return None
        try:
            size, mtime_ns, cached, depth, backend, error, strings, flat = row
            if not self._matches(file, size, mtime_ns, cached, digest):
                return None
            result = _decode(file, depth, backend, error, strings, flat)
        except (ValueError, TypeError, IndexError):
            return None
        del self._raw[file.path]
        self._entries[file.path] = (size, mtime_ns, cached, result)
        return result

    def put(self, file: RepositoryFile, result: ExtractionResult, digest: str | None = None) -> None:
        super().put(file, result, digest)
        self._raw.pop(file.path, None)
        self._dirty.add(self._shard(file.path))

    def prune(self, live_paths: set[str]) -> None:
        for path in (set(self._entries) | set(self._raw)) - live_paths:
            self._entries.pop(path, None)
            self._raw.pop(path, None)
            self._dirty.add(self._shard(path))

    def known_files(self) -> dict[str, tuple[int, int]]:
        known = super().known_files()
        for path, row in self._raw.items():
            if isinstance(row, list) and len(row) >= 2:
                known.setdefault(path, (row[0], row[1]))
        return known

    def save(self) -> None:
        if not self._dirty:
            return
        rows: dict[int, dict[str, list]] = {shard: {} for shard in self._dirty}
        for path, row in self._raw.items():
            shard = self._shard(path)
            if shard in rows:
                rows[shard][path] = row
        for path, (size, mtime_ns, digest, result) in self._entries.items():
            shard = self._shard(path)
            if shard in rows:
                rows[shard][path] = [size, mtime_ns, digest, *_encode(result)]
        for shard in sorted(rows):
            if self._write(shard, rows[shard]):
                self._dirty.discard(shard)

    def _write(self, shard: int, entries: dict[str, list]) -> bool:
        payload = {"version": _FORMAT_VERSION, "shards": self.shards, "entries": dict(sorted(entries.items()))}
        tmp = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".meu_coding-", dir=self.directory)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            os.replace(tmp, self._shard_file(shard))
            return True
        except OSError as exc:
            logger.warning("could not save meu_coding cache shard %s: %s", shard, exc)
            if tmp is not None and os.path.exists(tmp):
                os.unlink(tmp)
            return False


def _encode(result: ExtractionResult) -> list:
    strings: dict[str, int] = {}

    def index(value: str | None) -> int:
        if value is None:
            return -1
        return strings.setdefault(value, len(strings))

    flat: list[int] = []
    for s in result.symbols:
        flat += [_KIND_CODES[s.kind], index(s.name), s.line,
                 -1 if s.column is None else s.column, index(s.container),
                 -1 if s.end_line is None else s.end_line]
    return [result.depth, result.backend, result.error, list(strings), flat]


def _decode(file: RepositoryFile, depth: str, backend: str, error: str | None,
            strings: list[str], flat: list[int]) -> ExtractionResult:
    if len(flat) % _FIELDS:
        raise ValueError("truncated symbol rows")
    path, language = file.path, file.language
    symbols = tuple(
        Symbol(strings[flat[i + 1]], _KINDS[flat[i]], path, flat[i + 2], language,
               None if flat[i + 3] < 0 else flat[i + 3],
               None if flat[i + 4] < 0 else strings[flat[i + 4]],
               None if flat[i + 5] < 0 else flat[i + 5])
        for i in range(0, len(flat), _FIELDS)
    )
    return ExtractionResult(path, symbols, backend, error, depth or DEEP)
