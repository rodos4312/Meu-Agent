"""Keep model catalogs for recently probed endpoints and Codex credentials in memory."""

import threading
import time
from typing import Any

# Same cap as the Codex service tier catalog, which uses the same fingerprint.
_MAX_CATALOGS = 128
_MEMO_LOCK = threading.Lock()


def cached_endpoint_models(memo_key: tuple[str, str]) -> dict[str, dict[str, Any]] | None:
    from agent import model_metadata as mm

    with _MEMO_LOCK:
        stamp = mm._endpoint_model_metadata_cache_time.get(memo_key, 0)
        if time.time() - stamp < mm._ENDPOINT_MODEL_CACHE_TTL:
            return mm._endpoint_model_metadata_cache.get(memo_key)
    return None


def remember_endpoint_models(memo_key: tuple[str, str], catalog: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from agent import model_metadata as mm

    with _MEMO_LOCK:
        now = time.time()
        values, stamps = mm._endpoint_model_metadata_cache, mm._endpoint_model_metadata_cache_time
        for key in [key for key in values if now - stamps.get(key, 0) >= mm._ENDPOINT_MODEL_CACHE_TTL]:
            values.pop(key)
            stamps.pop(key, None)
        if memo_key not in values and len(values) >= _MAX_CATALOGS:
            oldest = min(values, key=lambda key: stamps.get(key, 0))
            values.pop(oldest)
            stamps.pop(oldest, None)
        values[memo_key], stamps[memo_key] = catalog, now
    return catalog


def _evict_codex_catalog(mm: Any, key: str) -> None:
    """Make space under the memo lock and remove the matching context cap."""
    values = mm._codex_oauth_context_cache
    if key not in values and len(values) >= _MAX_CATALOGS:
        oldest = min(values, key=lambda item: values[item][1])
        values.pop(oldest)
        mm._codex_oauth_max_context_cache.pop(oldest, None)


def remember_no_codex_catalog(key: str) -> None:
    """A failed probe gets a short TTL and cannot replace a fresh successful probe."""
    from agent import model_metadata as mm

    with _MEMO_LOCK:
        now = time.time()
        ttl = mm._CODEX_OAUTH_CONTEXT_CACHE_TTL
        current = mm._codex_oauth_context_cache.get(key)
        if current is not None and current[0] and now - current[1] < ttl:
            return
        _evict_codex_catalog(mm, key)
        mm._codex_oauth_context_cache[key] = ({}, now - ttl + mm._CODEX_OAUTH_CONTEXT_NEGATIVE_TTL)


def remember_codex_catalog(key: str, lengths: dict[str, int], caps: dict[str, int], now: float) -> None:
    from agent import model_metadata as mm

    with _MEMO_LOCK:
        _evict_codex_catalog(mm, key)
        # Publish caps first so a reader that sees the new catalog can also see its cap.
        mm._codex_oauth_max_context_cache[key] = caps
        mm._codex_oauth_context_cache[key] = (lengths, now)
