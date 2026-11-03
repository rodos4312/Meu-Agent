"""Direct, hash-pinned dependency sources with a user's optional npm registry."""
from pathlib import Path
import os

from pm.downloader import Source
from pm.index_config import npm_registry_url


def pinned_source(url: str, dest: Path, sha256: str) -> Source:
    return Source(npm_registry_url(url, os.environ), dest, sha256)
