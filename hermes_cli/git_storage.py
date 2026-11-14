"""Git object publication for PRoot's emulated-hard-link filesystem."""
from __future__ import annotations

import platform


def git_storage_overrides(kernel_release: str | None = None) -> list[tuple[str, str]]:
    """Apply only on a PRoot kernel; internal Git deliberately ignores global config."""
    release = platform.release() if kernel_release is None else kernel_release
    return [("core.createObject", "rename")] if "proot" in release.lower() else []
