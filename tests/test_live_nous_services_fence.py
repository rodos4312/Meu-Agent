"""No test reaches a live Nous service unless it is a ``live`` canary (``tests/conftest.py``).

A test home has no Nous identity, so a hosted connector action used to mint a real guest on
the production Portal: seconds per test, red when the Portal was slow, and a new production
guest on every CI run.
"""

import socket

import pytest


def test_retired_connector_action_mints_no_portal_guest():
    import json
    from hermes_cli import anon_auth
    from tools.connectors.tool import manage_connections
    result = json.loads(manage_connections({"action": "connect", "connectors": ["gmail"]}))
    assert "Hosted accounts are not supported" in result["error"]
    assert not anon_auth.has_guest()


@pytest.mark.parametrize("host", ["portal.nousresearch.com", "inference-api.nousresearch.com",
                                  b"WELCOME-API.NOUSRESEARCH.COM.", "telemetry.staging-nousresearch.com"])
def test_nous_hosts_are_refused_at_the_name_lookup(host):
    with pytest.raises(socket.gaierror, match="test fence"):
        socket.getaddrinfo(host, 443)
