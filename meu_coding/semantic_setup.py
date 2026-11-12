"""Build a project's ``RepositoryIntelligence`` with the optional semantic layer attached.

The layer comes from ``coding_engine.semantic`` in the active profile's config.yaml; its
store is one SQLite file per project under ``<HERMES_HOME>/coding_semantic/``. Any failure
here yields a disabled layer with a reason; the structural index is built regardless.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from meu_coding.embeddings import resolve_embedding_provider, semantic_settings
from meu_coding.intelligence import RepositoryIntelligence
from meu_coding.semantic_index import SemanticIndex, SemanticLayer, disabled_layer, store_path

logger = logging.getLogger(__name__)


def semantic_layer_for(project_root: str, config: Mapping[str, Any] | None = None,
                       home: str | Path | None = None) -> SemanticLayer:
    if config is None:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly() or {}
    choice = resolve_embedding_provider(config)
    if choice.provider is None:
        return SemanticLayer(None, choice.status, choice.reason)
    if home is None:
        from hermes_constants import get_hermes_home

        home = get_hermes_home()
    try:
        index = SemanticIndex(project_root, choice.provider, store_path(home, project_root),
                              include_tests=bool(semantic_settings(config).get("include_tests")))
    except (sqlite3.Error, OSError) as exc:
        logger.warning("semantic index unavailable", exc_info=True)
        return disabled_layer(f"Semantic index could not be opened: {type(exc).__name__}")
    return SemanticLayer(index, "enabled", choice.reason)


def build_intelligence(project_root: str) -> RepositoryIntelligence:
    intelligence = RepositoryIntelligence(project_root, semantic=semantic_layer_for(project_root))
    intelligence.analyze_repository()
    return intelligence
