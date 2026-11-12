"""Attribution default_headers applied per provider via base-URL detection.

Mirrors the OpenRouter pattern for the Vercel AI Gateway so that
referrerUrl / appName / User-Agent flow into gateway analytics.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hermes_cli.version_info import get_version_info
from run_agent import AIAgent


@patch("agent.process_bootstrap.OpenAI")
def test_nvidia_cloud_base_url_applies_billing_origin_header(mock_openai):
    mock_openai.return_value = MagicMock()
    agent = AIAgent(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/test-model",
        provider="nvidia",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )

    assert agent._client_kwargs["default_headers"]["X-BILLING-INVOKE-ORIGIN"] == "HermesAgent"

    agent._apply_client_headers_for_base_url("https://integrate.api.nvidia.com/v1")

    headers = agent._client_kwargs["default_headers"]
    assert headers["X-BILLING-INVOKE-ORIGIN"] == "HermesAgent"


@patch("agent.process_bootstrap.OpenAI")
def test_routed_client_preserves_openai_sdk_custom_headers(mock_openai):
    mock_openai.return_value = MagicMock()
    routed_client = SimpleNamespace(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        _custom_headers={"X-BILLING-INVOKE-ORIGIN": "HermesAgent"},
    )

    with patch("agent.auxiliary_client.resolve_provider_client", return_value=(
        routed_client,
        "nvidia/test-model",
    )):
        agent = AIAgent(
            provider="nvidia",
            model="nvidia/test-model",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )

    headers = agent._client_kwargs["default_headers"]
    assert headers["X-BILLING-INVOKE-ORIGIN"] == "HermesAgent"


# ---------------------------------------------------------------------------
# model.default_headers — user-configured overrides (#40033)
# ---------------------------------------------------------------------------


@patch("agent.process_bootstrap.OpenAI")
def test_user_default_headers_override_sdk_user_agent(mock_openai):
    """``model.default_headers`` lets a custom endpoint swap the OpenAI SDK
    User-Agent that some gateways/WAFs reject (the #40033 reproduction)."""
    mock_openai.return_value = MagicMock()
    agent = AIAgent(
        api_key="test-key",
        base_url="http://localhost:8080/v1",
        model="my-custom-model",
        provider="custom",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )

    with patch("hermes_cli.config.load_config", return_value={
        "model": {"default_headers": {"User-Agent": "curl/8.7.1", "X-Extra": "1"}},
    }), patch("hermes_cli.config.load_config_readonly", return_value={
        "model": {"default_headers": {"User-Agent": "curl/8.7.1", "X-Extra": "1"}},
    }):
        agent._apply_client_headers_for_base_url("http://localhost:8080/v1")

    headers = agent._client_kwargs["default_headers"]
    assert headers["User-Agent"] == "curl/8.7.1"
    assert headers["X-Extra"] == "1"

