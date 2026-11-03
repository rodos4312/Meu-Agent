#!/usr/bin/env -S bash -c 'exec "$BASH" "$(dirname "$0")/run-in-hermes-env" python3 "$0" "$@"'
"""Build the optional Meu model catalog from bundled provider lists."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, UTC

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Ensure HERMES_HOME is set for imports that touch it at module level.
os.environ.setdefault("HERMES_HOME", os.path.join(os.path.expanduser("~"), ".hermes"))

from hermes_cli.models import (
    OPENROUTER_MODELS,
    PREFERRED_SILENT_DEFAULT_MODEL,
    _PROVIDER_MODELS,
)

OUTPUT_PATH = os.path.join(REPO_ROOT, "website", "static", "api", "model-catalog.json")
CATALOG_VERSION = 1


def _openrouter_entry(mid: str, desc: str) -> dict:
    entry: dict = {"id": mid, "description": desc}
    if mid == PREFERRED_SILENT_DEFAULT_MODEL:
        entry["description"] = desc or "default"
        entry["default"] = True
    return entry


def _provider_entry(mid: str) -> dict:
    entry: dict = {"id": mid}
    if mid == PREFERRED_SILENT_DEFAULT_MODEL:
        entry["default"] = True
    return entry


def build_catalog() -> dict:
    return {
        "version": CATALOG_VERSION,
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "source": "Meu repository",
            "docs": "https://github.com/rodos4312/Meu-Agent/tree/dev/meu-foundation/website/docs/reference/model-catalog.md",
        },
        "providers": {
            "openrouter": {
                "metadata": {
                    "display_name": "OpenRouter",
                    "note": (
                        "Descriptions drive picker badges. Live /api/v1/models "
                        "filters curated ids by tool-calling support and free pricing. "
                        'The entry labeled "default": true is the model Hermes '
                        "silently lands on when the user never picked one."
                    ),
                },
                "models": [
                    _openrouter_entry(mid, desc)
                    for mid, desc in OPENROUTER_MODELS
                ],
            },
            "deepseek": {
                "metadata": {
                    "display_name": "DeepSeek",
                    "note": (
                        'The entry labeled "default": true is the model Hermes '
                        "silently lands on when the user never picked one."
                    ),
                },
                "models": [
                    _provider_entry(mid)
                    for mid in _PROVIDER_MODELS.get("deepseek", [])
                ],
            },
        },
    }


def main() -> int:
    catalog = build_catalog()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2)
        fh.write("\n")

    print(f"Wrote {OUTPUT_PATH}")
    for provider, block in catalog["providers"].items():
        print(f"  {provider}: {len(block['models'])} models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
