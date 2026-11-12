"""Project-scoped semantic chunk index, kept in step with the Phase 1 index.

There is no watcher here. ``RepositoryIntelligence`` already decides which files were added,
modified or removed (one source of truth); it calls :meth:`SemanticIndex.update_file` /
:meth:`SemanticIndex.remove_file` from the same per-file path that updates the repo index,
the graph and the relevance index, and :meth:`SemanticIndex.sync` after a full analysis.

Chunks follow the definitions the Phase 1 extractor already found (function, class, method,
module section); a file without definitions becomes short line-window chunks. A chunk is
re-embedded only when its identity changes: content hash, provider key (provider, model,
version, dimension) or :data:`CHUNKING_VERSION`. Vectors are reused by content hash, so a
renamed file or a moved function costs no embedding call.

What is stored: chunk metadata (path, symbol, container, language, line span, content hash,
source hash) and the vector. Never the source text, never anything secret: sensitive paths,
binaries and chunks that MEU's redactor would alter are not embedded at all.
"""

from __future__ import annotations

import hashlib
import logging
import os
import posixpath
import sqlite3
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from meu_coding.embeddings import EmbeddingProvider, EmbeddingUnavailable, EmbeddingVector, pack, unpack
from meu_coding.interfaces import ExtractionResult, RepositoryFile

logger = logging.getLogger(__name__)

CHUNKING_VERSION = "chunks-v1"
SCHEMA_VERSION = "2"
COMMIT_EVERY = 250
MAX_CHUNK_LINES = 80
WINDOW_LINES = 40
MIN_CHUNK_CHARS = 40
CHUNK_KINDS = frozenset({"function", "class", "method", "interface", "struct", "enum", "trait", "type"})
TEXT_LANGUAGES = frozenset({"markdown", "rst", "text", "yaml", "toml", "ini", "json"})

_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".der", ".crt", ".cer", ".gpg",
                    ".asc", ".kdbx", ".ppk", ".tfstate")
_SECRET_NAMES = frozenset({".env", ".envrc", ".netrc", ".pgpass", ".npmrc", ".pypirc", ".git-credentials",
                           "auth.json", "auth.lock", "credentials", "credentials.json", "secrets.json",
                           "secrets.yaml", "secrets.yml", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
                           "google_token.json", "token.json", "tokens.json"})
_SECRET_DIRS = frozenset({".ssh", ".gnupg", "mcp-tokens", "pairing", "secrets", ".aws", ".kube"})


def excluded_path(path: str) -> str | None:
    """Why ``path`` is never embedded (None when it may be)."""
    from meu_coding.repo_index import BINARY_EXTENSIONS
    from meu_coding.scope import is_protected

    name = posixpath.basename(path).lower()
    if is_protected(path):
        return "protected path"
    if name in _SECRET_NAMES or name.startswith(".env.") or name.endswith(_SECRET_SUFFIXES):
        return "credential or key file"
    if any(part.lower() in _SECRET_DIRS for part in path.split("/")[:-1]):
        return "credential directory"
    if posixpath.splitext(name)[1] in BINARY_EXTENSIONS:
        return "binary file"
    return None


def holds_secret(text: str) -> bool:
    """MEU's own redactor decides: a chunk it would alter is never embedded."""
    from agent.redact import redact_sensitive_text

    return redact_sensitive_text(text, force=True) != text


@dataclass(frozen=True)
class SemanticChunk:
    chunk_id: str
    path: str
    symbol: str
    container: str
    kind: str
    language: str
    start_line: int
    end_line: int
    content_hash: str
    text: str = field(repr=False, compare=False)  # embedded, never stored


def _digest(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def _header(path: str, symbol: str, container: str) -> str:
    owner = f"{container}.{symbol}" if container and symbol else symbol
    return f"{path} {owner}".strip()


def chunk_file(path: str, language: str, source: str, extraction: ExtractionResult | None) -> list[SemanticChunk]:
    """Deterministic chunks from the extractor's definition boundaries (or line windows)."""
    lines = source.splitlines()
    if not lines:
        return []
    starts = sorted({(s.line, s.name, s.container or "", s.kind) for s in (extraction.symbols if extraction else ())
                     if s.kind in CHUNK_KINDS and 1 <= s.line <= len(lines)})
    spans: list[tuple[int, int, str, str, str]] = []
    if starts and starts[0][0] > 1:
        spans.append((1, starts[0][0] - 1, "", "", "module"))
    for index, (line, name, container, kind) in enumerate(starts):
        end = (starts[index + 1][0] - 1) if index + 1 < len(starts) else len(lines)
        spans.append((line, max(line, end), name, container, kind))
    if not starts:
        size = WINDOW_LINES if language in TEXT_LANGUAGES or not extraction else MAX_CHUNK_LINES
        spans = [(i, min(i + size - 1, len(lines)), "", "", "section") for i in range(1, len(lines) + 1, size)]
    chunks = []
    for start, end, name, container, kind in spans:
        end = min(end, start + MAX_CHUNK_LINES - 1)
        body = "\n".join(lines[start - 1:end])
        if len(body.strip()) < MIN_CHUNK_CHARS:
            continue
        text = _header(path, name, container) + "\n" + body
        content_hash = _digest(text)
        chunk_id = _digest(f"{path}\0{start}\0{name}\0{content_hash}")[:32]
        chunks.append(SemanticChunk(chunk_id, path, name, container, kind, language, start, end, content_hash, text))
    return chunks


@dataclass
class IndexStats:
    chunks_total: int = 0
    embedded: int = 0
    reused: int = 0
    removed: int = 0
    skipped_files: int = 0
    skipped_chunks: int = 0
    seconds: float = 0.0
    files_updated: int = 0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, source_hash TEXT NOT NULL, provider_key TEXT NOT NULL,
                                  chunking TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY, path TEXT NOT NULL, symbol TEXT, container TEXT, kind TEXT, language TEXT,
  start_line INTEGER, end_line INTEGER, content_hash TEXT NOT NULL, provider_key TEXT NOT NULL,
  chunking TEXT NOT NULL, dimension INTEGER NOT NULL, vector BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
CREATE INDEX IF NOT EXISTS chunks_content ON chunks(content_hash, provider_key);
"""


def store_path(home: str | Path, project_root: str) -> Path:
    identity = os.path.normcase(os.path.realpath(project_root))
    return Path(home) / "coding_semantic" / f"{_digest('project:' + identity)[:24]}.sqlite"


class SemanticIndex:
    """One SQLite file per project (or ``:memory:``). Thread-safe through one lock."""

    def __init__(self, project_root: str, provider: EmbeddingProvider, location: str | Path = ":memory:",
                 include_tests: bool = False) -> None:
        self.project_root = project_root
        self.provider = provider
        self.location = str(location)
        # Tests are already linked structurally (test_relation); leaving them out halves a big index.
        self.include_tests = include_tests
        if self.location != ":memory:":
            Path(self.location).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.location, check_same_thread=False)
        self._migrate()
        self._lock = threading.Lock()
        self._pending = 0
        self._search_cache = None
        self.stats = IndexStats()
        self.last_error = ""
        self._vectors: dict[str, tuple[str, EmbeddingVector]] | None = None  # chunk_id → (path, vector)
        self._provider_key = ""

    def _migrate(self) -> None:
        """A store from another schema is rebuilt (it only holds derived data)."""
        try:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        except sqlite3.Error:
            row = None
        if row is None or row[0] != SCHEMA_VERSION:
            self._db.executescript("DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS meta;")
        self._db.executescript(_SCHEMA)
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (SCHEMA_VERSION,))
        self._db.commit()

    def _commit(self, force: bool = False) -> None:
        self._pending += 1
        if force or self._pending >= COMMIT_EVERY:
            self._db.commit()
            self._pending = 0

    # ── identity ────────────────────────────────────────────────────────────

    @property
    def provider_key(self) -> str:
        if not self._provider_key:
            self._provider_key = self.provider.identity.key
        return self._provider_key

    def _project_identity(self) -> str:
        return _digest("project:" + os.path.normcase(os.path.realpath(self.project_root)))[:24]

    # ── updates (called by RepositoryIntelligence) ──────────────────────────

    def sync(self, root: Path, files: Iterable[RepositoryFile], extractions: dict[str, ExtractionResult]) -> IndexStats:
        """After a full analysis: bring every file up to date, drop vanished ones. Unchanged files
        (same source hash, provider key and chunking version) cost one hash, no embedding."""
        started = time.perf_counter()
        self.stats = IndexStats()
        live = {f.path: f for f in files}
        with self._lock:
            known = {row[0] for row in self._db.execute("SELECT path FROM files")}
            for path in sorted(known - set(live)):
                self._remove_locked(path)
        with self._lock:
            unchanged = {row[0]: row[1:] for row in self._db.execute(
                "SELECT path, size, mtime_ns, provider_key, chunking FROM files")}
        for path in sorted(live):
            file = live[path]
            if unchanged.get(path) == (file.size, file.mtime_ns, self.provider_key, CHUNKING_VERSION):
                continue  # same metadata rule as the Phase 1 index: unchanged files are not read
            self._update(root, file, extractions.get(path))
        with self._lock:
            self._commit(force=True)
        self.stats.seconds = round(time.perf_counter() - started, 4)
        return self.stats

    def update_files(self, root: Path, files: Sequence[RepositoryFile],
                     extractions: dict[str, ExtractionResult]) -> IndexStats:
        started = time.perf_counter()
        self.stats = IndexStats()
        for file in files:
            self._update(root, file, extractions.get(file.path))
        with self._lock:
            self._commit(force=True)
        self.stats.seconds = round(time.perf_counter() - started, 4)
        return self.stats

    def remove_file(self, path: str) -> None:
        with self._lock:
            self._remove_locked(path)

    def _remove_locked(self, path: str) -> None:
        removed = self._db.execute("DELETE FROM chunks WHERE path = ?", (path,)).rowcount
        self._db.execute("DELETE FROM files WHERE path = ?", (path,))
        self._commit()
        self.stats.removed += max(removed, 0)
        if removed:
            self._vectors = None
            self._search_cache = None

    def _update(self, root: Path, file: RepositoryFile, extraction: ExtractionResult | None) -> None:
        from meu_coding.relevance import is_test_path

        if excluded_path(file.path) or (not self.include_tests and is_test_path(file.path)):
            self.stats.skipped_files += 1
            self.remove_file(file.path)
            return
        try:
            raw = (root / file.path).read_bytes()
        except OSError:
            self.remove_file(file.path)
            return
        if b"\0" in raw[:8192]:
            self.stats.skipped_files += 1
            self.remove_file(file.path)
            return
        source_hash = _digest(raw)
        with self._lock:
            row = self._db.execute("SELECT source_hash, provider_key, chunking FROM files WHERE path = ?",
                                   (file.path,)).fetchone()
        if row == (source_hash, self.provider_key, CHUNKING_VERSION):
            with self._lock:  # content identical (e.g. touched): only the metadata moves
                self._db.execute("UPDATE files SET size = ?, mtime_ns = ? WHERE path = ?",
                                 (file.size, file.mtime_ns, file.path))
                self._commit()
            return
        chunks = chunk_file(file.path, file.language, raw.decode("utf-8", errors="replace"), extraction)
        safe = [c for c in chunks if not holds_secret(c.text)]
        self.stats.skipped_chunks += len(chunks) - len(safe)
        self._replace_file(file, source_hash, safe)
        self.stats.files_updated += 1

    def _replace_file(self, file: RepositoryFile, source_hash: str, chunks: list[SemanticChunk]) -> None:
        path = file.path
        key = self.provider_key
        with self._lock:
            existing = {r[0]: r[1] for r in self._db.execute(
                "SELECT chunk_id, provider_key FROM chunks WHERE path = ?", (path,))}
            keep = {c.chunk_id for c in chunks if existing.get(c.chunk_id) == key}
            reuse: dict[str, bytes] = {}
            for chunk in chunks:
                if chunk.chunk_id in keep:
                    continue
                found = self._db.execute(
                    "SELECT vector FROM chunks WHERE content_hash = ? AND provider_key = ? AND chunking = ? LIMIT 1",
                    (chunk.content_hash, key, CHUNKING_VERSION)).fetchone()
                if found:
                    reuse[chunk.chunk_id] = found[0]
        todo = [c for c in chunks if c.chunk_id not in keep and c.chunk_id not in reuse]
        vectors = self.provider.embed([c.text for c in todo]) if todo else []
        fresh = {c.chunk_id: pack(v) for c, v in zip(todo, vectors, strict=True)}
        with self._lock:
            stale = [cid for cid in existing if cid not in {c.chunk_id for c in chunks} or cid not in keep]
            self._db.executemany("DELETE FROM chunks WHERE chunk_id = ?", [(cid,) for cid in stale])
            rows = []
            for chunk in chunks:
                if chunk.chunk_id in keep:
                    continue
                blob = reuse.get(chunk.chunk_id) or fresh[chunk.chunk_id]
                rows.append((chunk.chunk_id, path, chunk.symbol, chunk.container, chunk.kind, chunk.language,
                             chunk.start_line, chunk.end_line, chunk.content_hash, key, CHUNKING_VERSION,
                             len(blob) // 2, blob))
            self._db.executemany("INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            self._db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)",
                             (path, source_hash, key, CHUNKING_VERSION, file.size, file.mtime_ns))
            self._db.execute("INSERT OR REPLACE INTO meta VALUES ('project', ?)", (self._project_identity(),))
            self._commit()
            if rows or stale:
                self._vectors = None
                self._search_cache = None
        self.stats.embedded += len(todo)
        self.stats.reused += len(reuse)
        self.stats.removed += len(stale) - len([c for c in stale if c in reuse or c in fresh])

    # ── reads ───────────────────────────────────────────────────────────────

    def vectors(self) -> dict[str, tuple[str, EmbeddingVector]]:
        with self._lock:
            if self._vectors is None:
                self._vectors = {cid: (path, unpack(blob)) for cid, path, blob in self._db.execute(
                    "SELECT chunk_id, path, vector FROM chunks WHERE provider_key = ? AND chunking = ?",
                    (self.provider_key, CHUNKING_VERSION))}
            return self._vectors

    def search_cache(self):
        """(paths, chunk_ids, vectors, by_file) for two-stage search; rebuilt only after changes."""
        with self._lock:
            if self._search_cache is None:
                rows = self._db.execute("SELECT chunk_id, path, vector FROM chunks WHERE provider_key = ? AND "
                                        "chunking = ? ORDER BY path, start_line",
                                        (self.provider_key, CHUNKING_VERSION)).fetchall()
                by_file: dict[str, list[int]] = {}
                for index, (_cid, path, _blob) in enumerate(rows):
                    by_file.setdefault(path, []).append(index)
                self._search_cache = ([r[1] for r in rows], [r[0] for r in rows], [unpack(r[2]) for r in rows],
                                      by_file)
            return self._search_cache

    def chunk(self, chunk_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT chunk_id, path, symbol, container, kind, language, start_line, end_line,"
                                   " content_hash, provider_key, chunking, dimension FROM chunks WHERE chunk_id = ?",
                                   (chunk_id,)).fetchone()
        if row is None:
            return None
        keys = ("chunk_id", "path", "symbol", "container", "kind", "language", "start_line", "end_line",
                "content_hash", "provider_key", "chunking", "dimension")
        return dict(zip(keys, row, strict=True))

    def chunks_for(self, path: str) -> list[dict]:
        with self._lock:
            ids = [r[0] for r in self._db.execute("SELECT chunk_id FROM chunks WHERE path = ? ORDER BY start_line",
                                                  (path,))]
        return [c for c in (self.chunk(i) for i in ids) if c]

    def counts(self) -> dict[str, int]:
        with self._lock:
            chunks = self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            files = self._db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        size = os.path.getsize(self.location) if self.location != ":memory:" and os.path.exists(self.location) else 0
        return {"chunks": chunks, "files": files, "bytes": size}

    def close(self) -> None:
        with self._lock:
            self._db.close()


class SemanticLayer:
    """The intelligence-facing facade: availability, the index and a last-error that never raises."""

    def __init__(self, index: SemanticIndex | None, status: str, reason: str) -> None:
        self.index = index
        self.status = status if index is not None else ("off" if status == "off" else "unavailable")
        self.reason = reason
        self.last_query_ms = 0.0

    @property
    def available(self) -> bool:
        return self.index is not None and self.status == "enabled"

    def _guard(self, action) -> None:
        if not self.available:
            return
        try:
            action()
        except EmbeddingUnavailable as exc:
            self.status, self.reason = "unavailable", str(exc)
        except (sqlite3.Error, OSError) as exc:
            logger.warning("semantic index update failed", exc_info=True)
            self.status, self.reason = "unavailable", f"semantic index error: {type(exc).__name__}"

    def sync(self, root: Path, files, extractions) -> None:
        self._guard(lambda: self.index.sync(root, files, extractions))

    def update_files(self, root: Path, files, extractions) -> None:
        self._guard(lambda: self.index.update_files(root, files, extractions))

    def remove_file(self, path: str) -> None:
        self._guard(lambda: self.index.remove_file(path))

    def describe(self) -> dict:
        out = {"status": self.status, "reason": self.reason, "last_query_ms": self.last_query_ms}
        if self.index is not None:
            identity = self.index.provider.identity if self.available else None
            if identity is not None:
                out.update({"provider": identity.label, "provider_key": identity.key, "kind": identity.kind})
            out.update(self.index.counts())
            out["last_update"] = dict(self.index.stats.__dict__)
        return out


def disabled_layer(reason: str = "Semantic search is off.") -> SemanticLayer:
    return SemanticLayer(None, "off", reason)
