"""Legacy endpoints cannot re-enter catalogs or inference through generic overrides."""
from unittest.mock import Mock

import pytest

from hermes_cli import model_catalog
from hermes_cli.auth import AuthError
from hermes_cli.config_backend import Changes, ConfigBackendUnavailable, ConfigValueError
from hermes_cli.meu_privacy import validate_independent_changes, validate_independent_config
from hermes_cli.runtime_provider import resolve_runtime_provider

RETIRED = [
    "https://hermes-agent.nousresearch.com/docs/api/model-catalog.json?revision=old",
    "https://PORTAL.NOUSRESEARCH.COM./v1/models",
    "https://inference-api.nousresearch.com/v1",
    "https://telemetry.staging-nousresearch.com/v1/telemetry",
    "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/static/api/model-catalog.json?ref=old",
]

@pytest.mark.parametrize("url", RETIRED)
def test_catalog_settings_are_rejected_without_migration(url):
    document = {"model_catalog": {"url": url, "providers": {"deepseek": {"url": url}}},
                "model": {"provider": "deepseek"}, "mcp_servers": {"local": {"command": "test-mcp"}}}
    with pytest.raises(ConfigBackendUnavailable, match="not supported"):
        validate_independent_config(document)
    assert document["model_catalog"]["url"] == url
    assert document["model"]["provider"] == "deepseek"

@pytest.mark.parametrize("url", RETIRED)
def test_catalog_fetch_refuses_retired_endpoints_before_network(monkeypatch, url):
    fetch = Mock(side_effect=AssertionError("Retired endpoint reached HTTP"))
    monkeypatch.setattr(model_catalog.urllib.request, "urlopen", fetch)
    assert model_catalog._fetch_manifest(url, timeout=1) is None
    fetch.assert_not_called()

@pytest.mark.parametrize("url", RETIRED)
def test_dotted_catalog_writes_cannot_restore_retired_urls(url):
    changes = Changes(set={"model_catalog.url": url,
        "model_catalog.providers.deepseek.url": url, "model.provider": "deepseek"})
    with pytest.raises(ConfigValueError, match="not supported"):
        validate_independent_changes(changes)
    assert changes.set["model_catalog.url"] == url

@pytest.mark.parametrize("url", ["https://portal.nousresearch.com/v1", "https://inference-api.nousresearch.com/v1"])
def test_generic_inference_override_cannot_restore_retired_service(url):
    with pytest.raises(AuthError, match="retired|Retired"):
        resolve_runtime_provider(requested="custom", explicit_api_key="test-only", explicit_base_url=url,
                                 target_model="test-model")

@pytest.mark.parametrize("url", ["https://api.deepseek.com/v1", "https://catalog.example.test/models.json",
                                  "https://nousresearch.com.example.test/models.json"])
def test_independent_catalog_endpoints_are_preserved(url):
    result = validate_independent_config({"model_catalog": {"url": url, "providers": {"custom": {"url": url}}}})
    assert result["model_catalog"]["url"] == url
    assert result["model_catalog"]["providers"]["custom"]["url"] == url


def test_saved_custom_endpoint_is_rejected_without_migration(tmp_path, monkeypatch):
    import hermes_yaml as yaml

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"model": {"provider": "custom", "default": "test-model",
        "base_url": "https://inference-api.nousresearch.com/v1"}}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ConfigBackendUnavailable, match="not supported"):
        resolve_runtime_provider(requested="custom", explicit_api_key="test-only", target_model="test-model")
    assert path.read_bytes() == before
