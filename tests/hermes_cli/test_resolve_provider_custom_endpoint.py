"""A configured custom (OpenAI-compatible) endpoint is explicit provider intent.

Regression for #108383: ``resolve_provider("auto")`` recognised only registry providers from
``model.provider``, so the boot inventory (``free_tier_bootstrap``) read a llama.cpp / vLLM /
ollama install as "nothing configured" and ``setup.status`` reported ``provider_configured:
False`` — the dashboard's Ink chat parked every new session on "Setup Required" while
``hermes chat`` (which resolves the runtime directly) worked against the same config.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / ".env").write_text("", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL",
                "OPENROUTER_BASE_URL", "HERMES_INFERENCE_PROVIDER", "PROVIDER_A_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("agent.bedrock_adapter.has_aws_credentials", lambda *_a, **_kw: False)
    from hermes_cli import free_tier_bootstrap as fb
    fb.reset_for_tests()
    return home


def test_auto_provider_with_loopback_base_url_resolves_without_recursing(isolated_home, monkeypatch):
    """A fresh setup keeps ``provider: auto`` until the picker stores its choice (#110926)."""
    (isolated_home / "config.yaml").write_text(
        "model:\n  provider: auto\n  base_url: http://127.0.0.1:8000/v1\n",
        encoding="utf-8",
    )
    from hermes_cli import runtime_provider
    from hermes_cli.auth import resolve_provider

    def unexpected_provider_resolution(_name):
        raise AssertionError("the bare custom trust check must not resolve model.provider=auto")

    monkeypatch.setattr(runtime_provider, "_resolves_to_custom", unexpected_provider_resolution)

    assert resolve_provider("auto") == "custom"

