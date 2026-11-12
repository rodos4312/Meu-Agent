"""Phase 7 semantic index: chunking from Phase 1 definitions, incremental updates through the ONE
change path of RepositoryIntelligence, vector reuse, invalidation, and what is never embedded."""

import sqlite3

from meu_coding.intelligence import RepositoryIntelligence
from meu_coding.semantic_index import CHUNKING_VERSION, SemanticIndex, SemanticLayer, excluded_path
from meu_coding.semantic_search import layer_search
from tests.meu_coding.phase7_support import ConceptEmbeddings, CountingLocal, FailingEmbeddings

FILES = {
    "net/link.py": "def reconnect_after_drop(session):\n    '''retry with backoff until the link is back'''\n"
                   "    return session.redial(backoff=2)\n\n\ndef close_link(session):\n"
                   "    '''close the session and release the socket handle'''\n    session.close()\n",
    "approvals/check.py": "def verify_digest(request, expected):\n    '''compare the checksum of the request'''\n"
                          "    return request.hash() == expected\n",
    "billing/invoice.py": "class Invoice:\n    def charge(self, amount):\n        '''charge the payment method'''\n"
                          "        return amount * 2\n",
    "README.md": "# Project\n\nThis project reconnects links and verifies digests of approval requests.\n",
}


def _intel(make_repo, tmp_path, provider, files=FILES, location=":memory:"):
    root = make_repo(files)
    layer = SemanticLayer(SemanticIndex(str(root), provider, location), "enabled", "test")
    intel = RepositoryIntelligence(root, semantic=layer)
    intel.analyze_repository()
    return root, intel, layer


def test_initial_index_chunks_by_definition_without_storing_source(make_repo, tmp_path):
    provider = ConceptEmbeddings()
    store = tmp_path / "sem.sqlite"
    _root, _unused, layer = _intel(make_repo, tmp_path, provider, location=store)
    chunks = layer.index.chunks_for("net/link.py")
    assert [c["symbol"] for c in chunks] == ["reconnect_after_drop", "close_link"]
    assert chunks[0]["start_line"] == 1 and chunks[0]["end_line"] < chunks[1]["start_line"]
    assert all(c["chunking"] == CHUNKING_VERSION and c["provider_key"] == provider.identity.key for c in chunks)
    raw = store.read_bytes()
    assert b"release the socket handle" not in raw and b"session.redial" not in raw  # no source text stored


def test_one_file_change_reembeds_only_that_files_changed_chunks(make_repo, tmp_path):
    provider = ConceptEmbeddings()
    root, intel, layer = _intel(make_repo, tmp_path, provider)
    before = len(provider.texts)
    target = root / "net/link.py"
    target.write_text(FILES["net/link.py"].replace("release the socket handle", "release every socket handle and"
                                                                                 " log it"), encoding="utf-8")
    changes = intel.refresh_changed_files(["net/link.py"])
    assert changes.modified == ("net/link.py",)
    embedded = provider.texts[before:]
    assert len(embedded) == 1 and "close_link" in embedded[0]  # the unchanged function was not re-embedded
    assert layer.index.stats.files_updated == 1 and layer.index.counts()["files"] == 4


def test_unchanged_refresh_and_restart_embed_nothing(make_repo, tmp_path):
    provider = ConceptEmbeddings()
    store = tmp_path / "sem.sqlite"
    root, intel, _layer = _intel(make_repo, tmp_path, provider, location=store)
    calls = provider.calls
    intel.refresh_changed_files()
    restarted = RepositoryIntelligence(root, semantic=SemanticLayer(SemanticIndex(str(root), provider, store),
                                                                    "enabled", "test"))
    restarted.analyze_repository()
    assert provider.calls == calls  # cached startup: same hashes, same provider key → no embedding


def test_deleted_file_loses_its_chunks(make_repo, tmp_path):
    root, intel, layer = _intel(make_repo, tmp_path, ConceptEmbeddings())
    (root / "billing/invoice.py").unlink()
    intel.refresh_changed_files()
    assert layer.index.chunks_for("billing/invoice.py") == []
    assert all(path != "billing/invoice.py" for path, _ in layer.index.vectors().values())


def test_renamed_file_reuses_vectors_without_embedding(make_repo, tmp_path):
    provider = ConceptEmbeddings()
    root, intel, layer = _intel(make_repo, tmp_path, provider)
    source = (root / "approvals/check.py").read_text(encoding="utf-8")
    (root / "approvals/check.py").unlink()
    (root / "approvals/verify.py").write_text(source, encoding="utf-8")
    texts = len(provider.texts)
    intel.refresh_changed_files()
    assert layer.index.chunks_for("approvals/check.py") == []
    assert [c["symbol"] for c in layer.index.chunks_for("approvals/verify.py")] == ["verify_digest"]
    # the header names the path, so a rename changes the chunk text: only that chunk is re-embedded
    assert len(provider.texts) - texts == 1


def test_model_or_version_change_recomputes_and_ignores_old_vectors(make_repo, tmp_path):
    store = tmp_path / "sem.sqlite"
    root, _unused, layer = _intel(make_repo, tmp_path, ConceptEmbeddings("concept-v1"), location=store)
    old = len(layer.index.vectors())
    upgraded = ConceptEmbeddings("concept-v2")
    intel2 = RepositoryIntelligence(root, semantic=SemanticLayer(SemanticIndex(str(root), upgraded, store),
                                                                 "enabled", "test"))
    intel2.analyze_repository()
    assert len(upgraded.texts) == old  # every chunk recomputed once for the new identity
    keys = {c["provider_key"] for p in ("net/link.py", "README.md") for c in intel2.semantic.index.chunks_for(p)}
    assert keys == {upgraded.identity.key}


def test_secrets_keys_and_binaries_are_never_embedded(make_repo, tmp_path):
    provider = CountingLocal()
    files = dict(FILES)
    files.update({".env": "API_KEY=sk-abcdefghijklmnopqrstuvwxyz0123456789\n",
                  "deploy/id_rsa": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----\n",
                  "certs/server.pem": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n",
                  "config/settings.py": "def token_config():\n    '''external client configuration'''\n"
                                        "    return 'sk-abcdefghijklmnopqrstuvwxyz0123456789'\n",
                  "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
                  "data/blob.bin": b"\x00\x01\x02" * 50})
    _root, _unused, layer = _intel(make_repo, tmp_path, provider, files=files)
    embedded = "\n".join(provider.texts)
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in embedded and "PRIVATE KEY" not in embedded
    for path in (".env", "deploy/id_rsa", "certs/server.pem", "assets/logo.png", "data/blob.bin"):
        assert layer.index.chunks_for(path) == [], path
    assert layer.index.chunks_for("config/settings.py") == []  # the only chunk holds a secret
    assert excluded_path("keys/release.jks") and excluded_path(".ssh/config") and not excluded_path("net/link.py")


def test_metadata_is_deterministic(make_repo, tmp_path):
    first = _intel(make_repo, tmp_path / "a", ConceptEmbeddings())[2].index.chunks_for("net/link.py")
    second = _intel(lambda f: make_repo(f), tmp_path / "b", ConceptEmbeddings())[2].index.chunks_for("net/link.py")
    assert first == second


def test_semantic_search_finds_differently_worded_code(make_repo, tmp_path):
    _root, _unused, layer = _intel(make_repo, tmp_path, ConceptEmbeddings())
    hits = layer_search(layer, "how is a lost connection resumed", 3)  # no word of the file in the query
    assert hits[0].path == "net/link.py" and hits[0].symbol in ("reconnect_after_drop", "close_link")
    assert len(hits[0].to_dict()["lines"]) == 2 and "semantic similarity" in hits[0].reason


def test_unavailable_provider_degrades_to_structural_only(make_repo, tmp_path):
    root = make_repo(FILES)
    layer = SemanticLayer(SemanticIndex(str(root), FailingEmbeddings(), ":memory:"), "enabled", "test")
    intel = RepositoryIntelligence(root, semantic=layer)
    intel.analyze_repository()
    assert layer.status == "unavailable" and "provider down" in layer.reason
    assert layer_search(layer, "reconnect", 5) == []  # no fake hits
    ranked = intel.rank("reconnect_after_drop")
    assert ranked[0].path == "net/link.py" and intel.last_ranking["semantic_status"] == "unavailable"


def test_disabled_layer_changes_nothing_in_structural_ranking(make_repo, tmp_path):
    root = make_repo(FILES)
    plain = RepositoryIntelligence(root)
    plain.analyze_repository()
    off = RepositoryIntelligence(root, semantic=SemanticLayer(None, "off", "off"))
    off.analyze_repository()
    assert [(r.path, r.score) for r in plain.rank("verify_digest request")] == \
        [(r.path, r.score) for r in off.rank("verify_digest request")]


def test_store_is_project_scoped_sqlite(make_repo, tmp_path):
    from meu_coding.semantic_index import store_path

    a, b = store_path(tmp_path, str(tmp_path / "one")), store_path(tmp_path, str(tmp_path / "two"))
    assert a != b and a.parent == b.parent == tmp_path / "coding_semantic"
    _intel(make_repo, tmp_path, ConceptEmbeddings(), location=a)
    tables = {r[0] for r in sqlite3.connect(a).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"meta", "files", "chunks"}


def test_tests_are_left_to_the_structural_graph_unless_included(make_repo, tmp_path):
    files = dict(FILES, **{"tests/test_link.py": "def test_reconnect():\n    '''retry and backoff are covered'''\n"
                                                 "    assert True\n"})
    root = make_repo(files)
    default = SemanticIndex(str(root), ConceptEmbeddings(), ":memory:")
    RepositoryIntelligence(root, semantic=SemanticLayer(default, "enabled", "t")).analyze_repository()
    assert default.chunks_for("tests/test_link.py") == []
    included = SemanticIndex(str(root), ConceptEmbeddings(), ":memory:", include_tests=True)
    RepositoryIntelligence(root, semantic=SemanticLayer(included, "enabled", "t")).analyze_repository()
    assert [c["symbol"] for c in included.chunks_for("tests/test_link.py")] == ["test_reconnect"]


def test_unchanged_files_are_not_even_read_on_startup(make_repo, tmp_path, monkeypatch):
    from pathlib import Path

    store = tmp_path / "sem.sqlite"
    root, _unused, _layer = _intel(make_repo, tmp_path, ConceptEmbeddings(), location=store)
    reads = []
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: reads.append(self.name) or original(self))
    layer = SemanticLayer(SemanticIndex(str(root), ConceptEmbeddings(), store), "enabled", "t")
    layer.sync(root, RepositoryIntelligence(root).indexer.scan(), {})
    assert reads == [] and layer.index.stats.files_updated == 0
