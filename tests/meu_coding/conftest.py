from pathlib import Path

import pytest


def write_tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return root


def build_graph(root: Path):
    from meu_coding.graph import RepositoryGraph
    from meu_coding.repo_index import RepositoryIndexer, read_source
    from meu_coding.symbols import SymbolExtractor

    files = RepositoryIndexer(root).scan()
    extractor = SymbolExtractor()
    extractions = {f.path: extractor.extract(f.path, read_source(root, f.path), f.language) for f in files}
    return RepositoryGraph(files, extractions)


@pytest.fixture
def make_repo(tmp_path):
    def _make(files: dict[str, str | bytes]) -> Path:
        return write_tree(tmp_path / "repo", files)
    return _make
