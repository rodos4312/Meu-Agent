"""Long-lived gateways should release catalogs for expired or rotated credentials."""

from agent import model_metadata as mm


def test_endpoint_cache_prunes_expired_entries_and_bounds_a_burst(monkeypatch):
    now = 1_000_000.0
    monkeypatch.setattr(mm.time, "time", lambda: now)
    endpoint = "http://127.0.0.1:8890/v1"
    expired = (endpoint, "expired")
    values = {expired: {"m": {"context_length": 100}}}
    stamps = {expired: now - mm._ENDPOINT_MODEL_CACHE_TTL - 1}
    monkeypatch.setattr(mm, "_endpoint_model_metadata_cache", values)
    monkeypatch.setattr(mm, "_endpoint_model_metadata_cache_time", stamps)

    for i in range(140):
        now += 1
        mm._remember_endpoint_models((endpoint, str(i) if i < 139 else ""), {"m": {"context_length": i}})

    assert expired not in values
    assert len(values) == 128
    assert values.keys() == stamps.keys()
    assert (endpoint, "0") not in values
    assert mm.fetch_endpoint_model_metadata(endpoint, api_key="") == {"m": {"context_length": 139}}


def test_codex_cache_evicts_the_oldest_context_and_its_companion(monkeypatch):
    values = {f"token{i}": ({"m": 100}, 1000.0 + i) for i in range(128)}
    caps = {key: {"m": 200} for key in values}
    monkeypatch.setattr(mm, "_codex_oauth_context_cache", values)
    monkeypatch.setattr(mm, "_codex_oauth_max_context_cache", caps)

    mm._remember_no_codex_catalog("new-token")

    assert len(values) == 128
    assert "token0" not in values and "token0" not in caps
    assert values["new-token"][0] == {} and caps["token127"]["m"] == 200

    mm._remember_no_codex_catalog("token127")
    assert len(values) == 128 and "token1" in values and caps["token127"]["m"] == 200
