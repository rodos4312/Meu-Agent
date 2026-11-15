"""Both transport modes refuse retired services before creating SDK fallback clients."""
from unittest.mock import Mock

import httpx
import pytest

from agent.process_bootstrap import build_keepalive_http_client
from hermes_cli.auth import AuthError

@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("url", ["https://inference-api.nousresearch.com/v1", "https://PORTAL.NOUSRESEARCH.COM./v1"])
def test_retired_transport_does_not_degrade_to_sdk_default(monkeypatch, url, async_mode):
    construct = Mock(side_effect=AssertionError("HTTP client must not be constructed"))
    monkeypatch.setattr(httpx, "Client", construct)
    monkeypatch.setattr(httpx, "AsyncClient", construct)
    with pytest.raises(AuthError, match="Retired"):
        build_keepalive_http_client(url, async_mode=async_mode)
    construct.assert_not_called()
