"""N86: every legacy-fallback verb from a ticket bound to a secondary profile runs in THAT profile.

Only ``@_profile_scoped`` handlers and two hand-fixed ones read the connection's profile; the
account connector path (``_profile_home(request.profile)`` with no ``profile``) and billing (which
ignores ``profile`` and resolves the Nous token through the runtime scope) ran in the launch
profile, so bee's Ink connected accounts and charged top-ups on default's portal account.
"""
import threading
import types
from pathlib import Path

import pytest


@pytest.fixture
def homes(tmp_path, monkeypatch):
    from tui_gateway import server
    launch = tmp_path / 'root'
    bee = launch / 'profiles' / 'bee'
    bee.mkdir(parents=True)
    monkeypatch.setenv('HERMES_HOME', str(launch))
    monkeypatch.setattr(server, '_hermes_home', launch)
    return server, launch, bee


def _call(server, profile_id, method, params):
    from gateway.runtime_bootstrap import _PURPOSE_CAPABILITIES
    from tui_gateway.ws_legacy_fallback import dispatch_legacy
    actor = types.SimpleNamespace(profile_id=str(profile_id), capabilities=frozenset(_PURPOSE_CAPABILITIES['interactive']))
    written, done = [], threading.Event()
    transport = types.SimpleNamespace(write=lambda frame: written.append(frame) or done.set() or True)
    reply = dispatch_legacy(server, {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, transport, actor)
    return reply if reply is not None else (done.wait(10) and written[0])


def test_secondary_ticket_runs_mcp_in_its_own_profile(homes, monkeypatch):
    from hermes_constants import get_hermes_home
    from hermes_cli import config
    server, launch, bee = homes
    seen = []
    def read_config(*args, **kwargs):
        seen.append(Path(str(get_hermes_home())).resolve())
        return {"mcp_servers": {}}
    monkeypatch.setattr(config, "load_config", read_config)
    reply = _call(server, bee, "mcp.servers.list", {})
    assert "result" in reply, reply
    assert seen and set(seen) == {bee.resolve()}
    seen.clear()
    reply = _call(server, launch, "mcp.servers.list", {})
    assert "result" in reply, reply
    assert seen and set(seen) == {launch.resolve()}


def test_ticket_whose_home_vanished_is_refused_not_the_launch_profile(homes):
    server, _launch, bee = homes
    gone = bee.parent / 'gone'
    reply = _call(server, gone, 'mcp.servers.list', {})
    assert reply['error']['code'] == 4064, reply
