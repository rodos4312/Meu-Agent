"""Independent direct web selections persist; retired providers cannot be selected."""


import pytest


@pytest.fixture()
def client(monkeypatch, _isolate_hermes_home):
    starlette = pytest.importorskip("starlette.testclient")
    import hermes_state
    from hermes_constants import get_hermes_home
    from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")
    test_client = starlette.TestClient(app)
    test_client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return test_client


def test_web_capability_picks_persist_independently(client):
    from hermes_cli.config import load_config

    def put(**body):
        assert client.put("/api/tools/toolsets/web/provider", json=body).status_code == 200

    put(provider="Firecrawl", capability="search")
    put(provider="Tavily", capability="extract")
    config = load_config()["web"]
    assert config["search_backend"] == "firecrawl"
    assert config["extract_backend"] == "tavily"
    response = client.put("/api/tools/toolsets/web/provider", json={"provider": "Nous Subscription"})
    assert response.status_code == 400
    assert load_config()["web"] == config
    rows = client.get("/api/tools/toolsets/web/config").json()["providers"]
    assert "Nous Subscription" not in {row["name"] for row in rows}
