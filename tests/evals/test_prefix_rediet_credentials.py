"""Evaluation runners require explicit independent inference; no legacy auth fallback."""
import importlib.util
from pathlib import Path

import pytest

@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[2] / "evals" / "prefix_rediet" / "run.py"
    spec = importlib.util.spec_from_file_location("prefix_rediet_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize("key,url", [(None,None), ("test-key",None), (None,"https://api.deepseek.com/v1")])
def test_missing_explicit_credentials_never_reads_auth_json(runner, monkeypatch, key, url):
    for name,value in (("PRD_INFERENCE_KEY",key),("PRD_INFERENCE_URL",url)):
        monkeypatch.delenv(name,raising=False)
        if value is not None:
            monkeypatch.setenv(name,value)
    with pytest.raises(ValueError,match="PRD_INFERENCE_URL.*PRD_INFERENCE_KEY"):
        runner._inference_env()


def test_explicit_independent_provider_works_and_retired_secret_is_not_forwarded(runner, monkeypatch):
    monkeypatch.setenv("PRD_INFERENCE_URL","https://api.deepseek.com/v1")
    monkeypatch.setenv("PRD_INFERENCE_KEY","test-only")
    monkeypatch.setenv("NOUS_API_KEY","retired-test-only")
    env=runner._inference_env()
    assert env["PRD_INFERENCE_URL"] == "https://api.deepseek.com/v1"
    assert env["PRD_INFERENCE_KEY"] == "test-only"
    assert "NOUS_API_KEY" not in env


def test_explicit_retired_endpoint_is_refused(runner, monkeypatch):
    monkeypatch.setenv("PRD_INFERENCE_URL","https://inference-api.nousresearch.com/v1")
    monkeypatch.setenv("PRD_INFERENCE_KEY","test-only")
    with pytest.raises(ValueError,match="retired|Retired"):
        runner._inference_env()
