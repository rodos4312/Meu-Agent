"""Embedding providers for the semantic relevance signal (Phase 7).

Embeddings are an OPTIONAL discovery signal. Nothing in the Coding Engine requires them:
with no provider the semantic layer reports itself unavailable and the Phase 1 structural
intelligence works exactly as before.

Providers, chosen from ``coding_engine.semantic`` in the profile's config.yaml:

- ``off`` (default): semantic search disabled.
- ``local``: :class:`LocalSubwordEmbeddings`, a deterministic feature-hashing embedder over
  identifier sub-words, word pairs and character trigrams. No model download, no network.
  It is a lexical-semantic signal (it links ``reconnect``/``reconnection``/``ReconnectState``),
  not a neural model, and is labelled as such everywhere it is shown.
- any MEU provider name (``openai``, ``custom:<name>``, a local OpenAI-compatible runtime…)
  plus ``model``: :class:`MeuApiEmbeddings` through MEU's own client resolver
  (``agent.auxiliary_client.resolve_provider_client``), so credentials, base URLs and proxies
  are MEU's; nothing here reads, stores or logs a key.

The cache identity of a vector is ``ProviderIdentity.key`` (provider, model, version,
dimension) plus the chunk content hash and the chunking version; changing any of them
re-embeds only the affected chunks.
"""

from __future__ import annotations

import itertools
import logging
import math
import operator
import re
import struct
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

EmbeddingVector = tuple[float, ...]
MAX_INPUT_CHARS = 6_000
API_BATCH = 64


class EmbeddingUnavailable(Exception):
    """The provider cannot embed right now; the semantic layer degrades to structural-only."""


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    model: str
    version: str
    dimension: int
    kind: str  # "local-lexical" | "api"

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}:{self.version}:{self.dimension}"

    @property
    def label(self) -> str:
        if self.kind == "local-lexical":
            return "local sub-word similarity (no model)"
        return f"{self.provider} · {self.model}"


class EmbeddingProvider(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    def embed(self, texts: Sequence[str]) -> list[EmbeddingVector]: ...


def normalize(values: Sequence[float]) -> EmbeddingVector:
    norm = math.sqrt(sum(v * v for v in values))
    return tuple(v / norm for v in values) if norm else tuple(0.0 for _ in values)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Both vectors are unit length (every provider normalizes), so this is a dot product."""
    return sum(map(operator.mul, a, b))


def pack(vector: Sequence[float]) -> bytes:
    """Half precision: cosine ranking is unaffected and storage halves."""
    return struct.pack(f"<{len(vector)}e", *vector)


def unpack(blob: bytes) -> EmbeddingVector:
    return struct.unpack(f"<{len(blob) // 2}e", blob)


# ── local lexical-semantic embedder ──────────────────────────────────────────

_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SUFFIXES = ("ations", "ation", "ions", "ion", "ings", "ing", "ers", "er", "ed", "es", "s", "ly")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def subwords(text: str) -> list[str]:
    words = []
    for part in re.split(r"[^A-Za-z0-9]+", text):
        words += [w.lower() for w in _CAMEL.findall(part)]
    return [_stem(w) for w in words if len(w) > 1]


class LocalSubwordEmbeddings:
    """Deterministic signed feature hashing; identical input → identical vector everywhere."""

    VERSION = "subword-v2"

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity("local", "subword-hash", self.VERSION, self.dimension, "local-lexical")

    def _add(self, values: list[float], feature: str, weight: float) -> None:
        code = zlib.crc32(feature.encode("utf-8"))  # deterministic across processes, unlike hash()
        values[code % self.dimension] += weight if code & 0x80000000 else -weight

    def _vector(self, text: str) -> EmbeddingVector:
        values = [0.0] * self.dimension
        words = subwords(text[:MAX_INPUT_CHARS])
        for word in words:
            self._add(values, "w:" + word, 1.0)
            padded = f"^{word}$"
            for i in range(len(padded) - 2):
                self._add(values, "t:" + padded[i:i + 3], 0.35)
        for left, right in itertools.pairwise(words):
            self._add(values, f"b:{left}_{right}", 0.6)
        return normalize(values)

    def embed(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        return [self._vector(t) for t in texts]


# ── MEU provider (OpenAI-compatible embeddings endpoint) ────────────────────


class MeuApiEmbeddings:
    """Embeddings through MEU's own provider client; the key never passes through here."""

    def __init__(self, provider: str, model: str, *, client_factory=None) -> None:
        self.provider = provider
        self.model = model
        self._client_factory = client_factory or self._resolve_client
        self._client = None
        self._dimension = 0

    @staticmethod
    def _resolve_client(provider: str, model: str):
        from agent.auxiliary_client import resolve_provider_client

        client, _resolved = resolve_provider_client(provider, model, task="coding_semantic")
        return client

    def _ensure(self):
        if self._client is None:
            try:
                self._client = self._client_factory(self.provider, self.model)
            except Exception as exc:  # resolver failures keep the semantic layer off, with a reason
                logger.info("semantic: embedding client unavailable", exc_info=True)
                raise EmbeddingUnavailable(f"{self.provider} client unavailable: {type(exc).__name__}") from None
            if self._client is None or not hasattr(self._client, "embeddings"):
                raise EmbeddingUnavailable(f"{self.provider} has no embeddings endpoint")
        return self._client

    @property
    def identity(self) -> ProviderIdentity:
        if not self._dimension:
            self._dimension = len(self._call(["dimension probe"])[0])
        return ProviderIdentity(self.provider, self.model, "api", self._dimension, "api")

    def _call(self, batch: Sequence[str]) -> list[EmbeddingVector]:
        client = self._ensure()
        try:
            response = client.embeddings.create(model=self.model, input=[t[:MAX_INPUT_CHARS] for t in batch])
        except Exception as exc:  # provider error: degrade, never crash a coding task
            logger.info("semantic: embedding call failed", exc_info=True)
            raise EmbeddingUnavailable(f"{self.provider} embeddings failed: {type(exc).__name__}") from None
        data = sorted(response.data, key=lambda d: d.index)
        return [normalize(d.embedding) for d in data]

    def embed(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        vectors: list[EmbeddingVector] = []
        for start in range(0, len(texts), API_BATCH):
            vectors += self._call(texts[start:start + API_BATCH])
        if vectors and not self._dimension:
            self._dimension = len(vectors[0])
        return vectors


# ── resolution from config ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ProviderChoice:
    provider: EmbeddingProvider | None
    status: str  # "enabled" | "off" | "unavailable"
    reason: str


def semantic_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    engine = config.get("coding_engine") if isinstance(config, Mapping) else None
    section = engine.get("semantic") if isinstance(engine, Mapping) else None
    return dict(section) if isinstance(section, Mapping) else {}


def resolve_embedding_provider(config: Mapping[str, Any], *, has_credentials=None) -> ProviderChoice:
    settings = semantic_settings(config)
    name = str(settings.get("provider") or "off").strip()
    if name in ("", "off", "none", "false"):
        return ProviderChoice(None, "off", "Semantic search is off (coding_engine.semantic.provider).")
    if name == "local":
        return ProviderChoice(LocalSubwordEmbeddings(int(settings.get("dimension") or 256)), "enabled",
                              "Local sub-word similarity (no model, no network).")
    model = str(settings.get("model") or "").strip()
    if not model:
        return ProviderChoice(None, "unavailable", f"Choose an embedding model for {name} (coding_engine.semantic.model).")
    if has_credentials is None:
        from meu_coding.provider_adapter import provider_has_credentials as has_credentials
    if not name.startswith("custom") and not has_credentials(name):
        return ProviderChoice(None, "unavailable", f"No credentials are configured for {name}.")
    return ProviderChoice(MeuApiEmbeddings(name, model), "enabled", f"{name} · {model}")
