"""Optional model labels supplied by provider plugins."""
from typing import Any

def picker_row_suffix(provider_row: Any, model_id: str) -> str:
    if not isinstance(provider_row, dict):
        return ""
    return str((provider_row.get("model_labels") or {}).get(model_id) or "")
