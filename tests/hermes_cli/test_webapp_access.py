"""Remote Webapp access (``hermes_cli.webapp_access``, ``/api/webapp-access/*``).

Native Desktop changes only the gateway's Webapp settings, using its configured sign-in provider.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    """Native Desktop on this computer, calling the gateway's own listener as its Web Access pane
    does: one native grant per request."""
    from tests.hermes_cli.native_gateway_client import native_desktop_client

    return native_desktop_client(monkeypatch)


@pytest.fixture()
def restarts(monkeypatch):
    """Capture the gateway restart that applies the config instead of spawning it."""
    import hermes_cli.web_server_gateway as gw

    calls: list[str] = []

    def _restart(profile, *, what, label):
        calls.append(what)
        return {"restart_started": True}

    monkeypatch.setattr(gw, "_restart_gateway_after", _restart)
    return calls


@pytest.fixture()
def sign_in(monkeypatch):
    from hermes_cli import webapp_access
    from hermes_cli.dashboard_auth import clear_providers, register_provider
    from plugins.dashboard_auth.basic import BasicAuthProvider, hash_password

    clear_providers()
    register_provider(BasicAuthProvider(
        username="admin", password_hash=hash_password("test-password"), secret=b"s" * 32))
    monkeypatch.setattr(webapp_access, "lan_address", lambda: "192.168.1.50")
    try:
        yield
    finally:
        clear_providers()

@pytest.fixture(autouse=True)
def builds(monkeypatch):
    """Capture the Webapp bundle builds (``hermes_cli.webapp.prepare_webapp_renderer``) instead of
    compiling the renderer."""
    from hermes_cli import webapp

    roots: list = []

    def prepare(project_root, **_options):
        roots.append(project_root)
        return webapp.webapp_dist_dir(project_root)

    monkeypatch.setattr(webapp, "prepare_webapp_renderer", prepare)
    return roots


def _config() -> dict:
    from hermes_cli.config import load_config

    return load_config()


def _dashboard_setup() -> tuple[object, object]:
    """The standalone dashboard's own public URL, in config.yaml and in .env, as Web Access found it."""
    from hermes_cli.config import load_env, read_raw_config

    return read_raw_config().get("dashboard", {}).get("public_url"), load_env().get("HERMES_DASHBOARD_PUBLIC_URL")


def test_web_access_keeps_its_url_in_the_webapp_block_and_leaves_the_dashboard_alone(client, restarts, sign_in):
    """Start and stop write only ``webapp.*``: the own-URL mode pins ``webapp.public_url``, LAN mode
    drops it (its callback follows each request), and the standalone dashboard's
    ``dashboard.public_url`` and ``.env`` pin, which a tunnelled dashboard needs after a restart,
    stay exactly as the user set them."""
    from hermes_cli.config import save_config, save_env_value

    save_config({**_config(), "dashboard": {"public_url": "https://dashboard.example.test"}})
    save_env_value("HERMES_DASHBOARD_PUBLIC_URL", "https://dashboard.example.test")
    dashboard = _dashboard_setup()

    response = client.post("/api/webapp-access/start", json={"mode": "public", "public_url": "https://hermes.example.test"})
    assert response.status_code == 200, response.text

    assert {key: _config()["webapp"].get(key) for key in ("enabled", "host", "public_url")} == {
        "enabled": True, "host": "127.0.0.1", "public_url": "https://hermes.example.test"}
    assert response.json()["public_url"] == "https://hermes.example.test"
    assert _dashboard_setup() == dashboard

    assert client.post("/api/webapp-access/stop").status_code == 200
    assert _config()["webapp"]["enabled"] is False
    assert _dashboard_setup() == dashboard

    assert client.post("/api/webapp-access/start", json={"mode": "lan"}).status_code == 200

    assert _config()["webapp"]["host"] == "0.0.0.0"
    assert not _config()["webapp"].get("public_url")
    assert _dashboard_setup() == dashboard
    assert restarts == ["turning on Web Access", "turning off Web Access", "turning on Web Access"]


def test_start_without_a_provider_writes_and_restarts_nothing(client, restarts, monkeypatch):
    from hermes_cli import webapp_access
    from hermes_cli.dashboard_auth import clear_providers

    clear_providers()
    monkeypatch.setattr(webapp_access, "lan_address", lambda: "192.168.1.50")

    assert client.post("/api/webapp-access/start", json={"mode": "lan"}).status_code == 400

    assert restarts == []
    assert not _config().get("webapp", {}).get("enabled")


@pytest.mark.parametrize(("webapp", "mode"), [
    ({"enabled": True}, "local"),
    ({"enabled": True, "host": "::1"}, "local"),
    ({"enabled": True, "host": "0.0.0.0"}, "lan"),
    ({"enabled": True, "public_url": "https://hermes.example.test"}, "public"),
    ({"enabled": False, "host": "0.0.0.0", "public_url": "https://hermes.example.test"}, None),
])
def test_status_names_the_mode_the_config_serves(client, webapp, mode):
    """The pane's mode follows the config: the documented loopback setup (``webapp.enabled: true``)
    serves this computer only, a wildcard host serves the network, and ``webapp.public_url`` serves
    the user's own URL. A loopback Webapp is never shown as "My own URL" with no address."""
    from hermes_cli.config import save_config

    save_config({**_config(), "webapp": webapp})

    status = client.get("/api/webapp-access/status")
    assert status.status_code == 200, status.text
    assert status.json()["mode"] == mode


def test_start_keeps_a_custom_port_and_builds_the_addresses_on_it(client, restarts, sign_in):
    """A ``webapp.port`` the user chose (a second gateway on this machine needs its own) survives
    every start and stop, and the status use it, even while Web Access is off."""
    from hermes_cli.config import save_config

    save_config({**_config(), "webapp": {"enabled": False, "port": 9333}})
    assert client.get("/api/webapp-access/status").json()["port"] == 9333

    assert client.post("/api/webapp-access/start", json={"mode": "lan"}).status_code == 200

    assert _config()["webapp"]["port"] == 9333

    assert client.post("/api/webapp-access/stop").status_code == 200
    response = client.post("/api/webapp-access/start", json={"mode": "public", "public_url": "https://hermes.example.test"})
    assert response.status_code == 200, response.text
    assert _config()["webapp"]["port"] == 9333
    assert response.json()["port"] == 9333


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("public_url", [
    "https://user:secret@hermes.example.test",
    "https://hermes.example.test/?next=x",
    "https://hermes.example.test:99999",
    "hermes.example.test",
])
def test_status_never_shows_a_public_url_the_gateway_refuses(client, public_url, enabled):
    """The pane shows the ``webapp:`` block as the gateway reads it, with the gateway's own reader: a
    ``webapp.public_url`` the gateway refuses shows as none, whether the Webapp is on or off, and
    the port the user chose still shows."""
    from hermes_cli.config import save_config

    save_config({**_config(), "webapp": {"enabled": enabled, "port": 9333, "public_url": public_url}})

    status = client.get("/api/webapp-access/status").json()
    assert (status["enabled"], status["mode"], status["public_url"], status["port"]) == (False, None, "", 9333)


@pytest.mark.parametrize("public_url", [
    "https://hermes.example.test:99999",
    "https://hermes.example.test:0",
    "https://hermes.example.test/a@b",
    "https://hermes.example.test/a b",
])
def test_start_refuses_a_public_url_the_gateway_would_refuse(client, restarts, sign_in, public_url):
    """Start checks the URL with the gateway's own ``webapp.public_url`` reader (plus https on a host
    other devices reach), so it never saves and restarts onto a Webapp the gateway then
    keeps off."""
    response = client.post("/api/webapp-access/start", json={"mode": "public", "public_url": public_url})
    assert response.status_code == 400, response.text

    assert restarts == []
    assert not _config().get("webapp", {}).get("enabled")


def test_start_takes_the_public_url_as_typed(client, restarts, sign_in):
    """Spaces around the URL and a trailing slash are not part of the address."""
    response = client.post("/api/webapp-access/start", json={"mode": "public", "public_url": "  https://hermes.example.test/ "})
    assert response.status_code == 200, response.text

    assert _config()["webapp"]["public_url"] == "https://hermes.example.test"


@pytest.fixture()
def lan_browser(monkeypatch):
    """The gateway's Webapp on all interfaces behind password sign-in, and a browser on the LAN
    signed in with a cookie session."""
    import plugins.dashboard_auth.basic as basic_plugin
    from hermes_cli import web_server
    from hermes_cli.dashboard_auth import clear_providers, register_provider
    from hermes_cli.dashboard_auth.routes import _reset_password_rate_limit

    monkeypatch.delenv("HERMES_DASHBOARD_PUBLIC_URL", raising=False)
    for key, value in (("bound_host", "0.0.0.0"), ("bound_port", 9120), ("auth_required", True),
                       ("trusted_public_hosts", frozenset()), ("ui_surface", "webapp"),
                       ("listener_public_url", "")):
        monkeypatch.setattr(web_server.app.state, key, value, raising=False)
    clear_providers()
    register_provider(basic_plugin.BasicAuthProvider(
        username="admin", password_hash=basic_plugin.hash_password("hunter2"), secret=b"s" * 32))
    _reset_password_rate_limit()
    browser = TestClient(web_server.app, base_url="http://192.168.1.50:9120")
    login = browser.post("/auth/password-login", json={"provider": "basic", "username": "admin", "password": "hunter2"})
    assert login.status_code == 200, login.text
    yield browser
    clear_providers()


def test_a_browser_signed_in_over_the_network_cannot_use_web_access(lan_browser, restarts, sign_in):
    """Web Access decides what this machine exposes, so only its owner here may use it. A browser
    signed in behind the sign-in gate may be on another device: every Web Access route answers it
    403 and changes nothing, while the same session still reaches an ordinary route."""
    page = {"Origin": "http://192.168.1.50:9120", "Sec-Fetch-Site": "same-origin"}

    assert lan_browser.get("/api/config").status_code == 200
    assert lan_browser.get("/api/webapp-access/status").status_code == 403
    assert lan_browser.post("/api/webapp-access/start", json={"mode": "lan"}, headers=page).status_code == 403
    assert lan_browser.post("/api/webapp-access/stop?profile=default", headers=page).status_code == 403

    assert restarts == []
    assert not _config()["webapp"]["enabled"]


@pytest.fixture()
def webapp_tab(monkeypatch):
    """A tab of the default Webapp (loopback, no sign-in gate), which may be a browser on another
    machine through ``ssh -L 9120:127.0.0.1:9120``: it holds the browser credential, which on this
    listener is the loopback session token."""
    from hermes_cli import web_server

    for key, value in (("ui_surface", "webapp"), ("auth_required", False), ("bound_host", "127.0.0.1"),
                       ("trusted_public_hosts", frozenset())):
        monkeypatch.setattr(web_server.app.state, key, value, raising=False)
    tab = TestClient(web_server.app, base_url="http://127.0.0.1:9120", raise_server_exceptions=False)
    tab.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    yield tab
    tab.close()


def test_a_webapp_tab_cannot_use_web_access(webapp_tab, restarts, sign_in):
    """Web Access decides what this machine exposes, so only native Desktop on this computer may use
    it: each of its requests carries a one-use grant from the gateway's private control socket, which
    answers only this OS user, and no Origin, and a browser tab can present neither. The browser
    credential is not that proof, even where it is the loopback session token: every Web Access
    route answers a Webapp tab 403 and changes nothing (the pane being hidden in the browser is UI
    only)."""
    assert webapp_tab.get("/api/webapp-access/status").status_code == 403
    assert webapp_tab.post("/api/webapp-access/start", json={"mode": "lan"}).status_code == 403
    assert webapp_tab.post("/api/webapp-access/stop").status_code == 403
    assert webapp_tab.post("/api/webapp-access/restart").status_code == 403

    assert restarts == []
    assert not _config().get("webapp", {}).get("enabled")


def test_native_desktop_uses_web_access_on_the_webapps_own_listener(client, monkeypatch):
    """With the Webapp on, native Desktop dials the gateway's listener that serves it, and its Web
    Access pane keeps working there."""
    from hermes_cli import web_server

    monkeypatch.setattr(web_server.app.state, "ui_surface", "webapp", raising=False)

    assert client.get("/api/webapp-access/status").status_code == 200


def test_start_builds_the_webapp_bundle_before_turning_it_on(client, restarts, sign_in, builds):
    """Start builds the bundle the gateway serves (``apps/desktop/dist-webapp``) with the function
    ``hermes webapp`` uses, reusing it when current, so it never reports a Webapp with nothing to
    serve as running."""
    from hermes_cli.config import get_project_root

    assert client.post("/api/webapp-access/start", json={"mode": "lan"}).status_code == 200
    assert builds == [get_project_root()]
    assert restarts == ["turning on Web Access"]


def test_start_checks_sign_in_again_after_build(client, restarts, sign_in, monkeypatch):
    from hermes_cli import webapp
    from hermes_cli.dashboard_auth import clear_providers

    monkeypatch.setattr(webapp, "prepare_webapp_renderer", lambda *_args, **_kwargs: clear_providers())
    response = client.post("/api/webapp-access/start", json={"mode": "lan"})
    assert response.status_code == 400, response.text
    assert restarts == []
    assert not _config()["webapp"]["enabled"]


def test_a_failed_build_turns_nothing_on_and_says_how_to_build(client, restarts, sign_in, monkeypatch):
    """When the bundle cannot be built, Start writes nothing and
    restarts nothing, and its error names the command that builds the bundle."""
    from hermes_cli import webapp

    def fail(_project_root, **_options):
        raise webapp.WebappBuildError("Browser-hosted Desktop build failed: npm exited 1")

    monkeypatch.setattr(webapp, "prepare_webapp_renderer", fail)

    response = client.post("/api/webapp-access/start", json={"mode": "lan"})
    assert response.status_code == 400
    assert "npm exited 1" in response.json()["detail"]
    assert "hermes webapp --build-only" in response.json()["detail"]

    assert restarts == []
    assert not _config()["webapp"]["enabled"]


def test_other_requests_answer_while_start_builds(client, restarts, sign_in, monkeypatch):
    """A config request still answers while the Webapp bundle builds."""
    import threading

    from hermes_cli import webapp

    answered_during_step: list[list[int]] = []

    def ask_for_config(answers: list[int]) -> None:
        other = TestClient(client.app, raise_server_exceptions=False)
        answers.append(other.get("/api/config").status_code)

    def slow_step(*_args, **_options):
        answers: list[int] = []
        request = threading.Thread(target=ask_for_config, args=(answers,), daemon=True)
        request.start()
        request.join(timeout=10)
        answered_during_step.append(list(answers))

    monkeypatch.setattr(webapp, "prepare_webapp_renderer", slow_step)

    response = client.post("/api/webapp-access/start", json={"mode": "lan"})
    assert response.status_code == 200, response.text
    assert answered_during_step == [[200]]
    assert restarts == ["turning on Web Access"]


def test_restart_applies_the_saved_config_and_does_nothing_else(client, restarts, sign_in, builds):
    """The pane's "Restart gateway" (a saved change the gateway has not applied yet) restarts the
    gateway serving the profile and nothing else: no build or config
    write."""
    from hermes_cli.config import read_raw_config, save_config

    save_config({**_config(), "webapp": {"enabled": True, "host": "0.0.0.0"}})
    saved = read_raw_config()

    response = client.post("/api/webapp-access/restart")
    assert response.status_code == 200, response.text
    assert response.json()["restart_started"] is True
    assert response.json()["mode"] == "lan"
    assert restarts == ["applying Web Access"]

    assert builds == []
    assert read_raw_config() == saved


def test_a_restart_refused_by_a_running_chat_is_reported_as_busy(client, sign_in, monkeypatch):
    """When a running chat refuses the gateway restart, the change stays saved and the answer says
    so in a field the pane can word plainly (``restart_busy``), beside the CLI's own refusal text."""
    import hermes_cli.web_server_gateway as gw

    refusal = ("Refusing to restart the gateway: 1 live session(s) would be interrupted.\n"
               "    POST /api/gateway/restart?interrupt=true   # interrupts 1 live session(s)")
    monkeypatch.setattr(gw, "live_session_refusal", lambda _profile, _verb: refusal)

    response = client.post("/api/webapp-access/start", json={"mode": "lan"})
    assert response.status_code == 200, response.text
    assert response.json()["restart_started"] is False
    assert response.json()["restart_busy"] is True
    assert response.json()["enabled"] is True



def _lock_is_free(lock) -> bool:
    """Whether another thread can take *lock* now (the caller's own hold of an RLock does not count)."""
    import threading

    free: list[bool] = []

    def probe() -> None:
        taken = lock.acquire(timeout=1)
        if taken:
            lock.release()
        free.append(taken)

    other = threading.Thread(target=probe, daemon=True)
    other.start()
    other.join(5)
    return free == [True]


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_the_gateway_restart_and_status_run_outside_the_config_lock(client, sign_in, monkeypatch, action):
    """Start and Stop write the config under the config lock every config, skills and tools request
    takes, then restart the gateway and read its status outside that lock: the restart spawn and the
    status query (a control-socket round trip of up to 5 seconds) hold no other request up."""
    import hermes_cli.web_server_gateway as gw
    from hermes_cli import web_server, webapp_access

    lock = web_server._CONFIG_MUTATION_LOCK
    free_during: dict[str, bool] = {}

    def restart(_profile, *, what, label):
        free_during["restart"] = _lock_is_free(lock)
        return {"restart_started": True}

    real_state = webapp_access._gateway_state

    def gateway_state(home):
        free_during["status"] = _lock_is_free(lock)
        return real_state(home)

    monkeypatch.setattr(gw, "_restart_gateway_after", restart)
    monkeypatch.setattr(webapp_access, "_gateway_state", gateway_state)
    response = {"start": lambda: client.post("/api/webapp-access/start", json={"mode": "lan"}),
                "stop": lambda: client.post("/api/webapp-access/stop"),
                "restart": lambda: client.post("/api/webapp-access/restart")}[action]()
    assert response.status_code == 200, response.text
    assert free_during == {"restart": True, "status": True}


@pytest.mark.parametrize("second", ["stop", "public"])
def test_web_access_changes_run_one_at_a_time(client, restarts, sign_in, monkeypatch, second):
    """A second change waits while the first builds and applies its settings."""
    import threading

    from hermes_cli import webapp, webapp_access
    from hermes_cli.web_routers import webapp_access as routes

    class WatchedLock:
        """The routes' change lock, noting when a change found it held."""

        def __init__(self):
            self.lock, self.found_held = threading.Lock(), threading.Event()

        def acquire(self, blocking=True, timeout=-1):
            taken = self.lock.acquire(blocking, timeout)
            if not taken:
                self.found_held.set()
            return taken

        def release(self):
            self.lock.release()

    watched = WatchedLock()
    monkeypatch.setattr(routes, "_CHANGE_LOCK", watched)
    entered, release = threading.Event(), threading.Event()

    def hold(*_args, **_options):
        if not entered.is_set():
            entered.set()
            release.wait(20)

    monkeypatch.setattr(webapp, "prepare_webapp_renderer", hold)
    public_url = "https://hermes.example.test"
    requests = {"lan": ("/api/webapp-access/start", {"mode": "lan"}),
                "stop": ("/api/webapp-access/stop", None),
                "public": ("/api/webapp-access/start", {"mode": "public", "public_url": public_url})}
    answers: dict[str, int] = {}

    def send(name: str) -> None:
        # Each thread needs its own client on the same native-Desktop app, which mints a grant per request.
        other = TestClient(client.app, raise_server_exceptions=False)
        path, body = requests[name]
        answers[name] = other.post(path, json=body).status_code

    first = threading.Thread(target=send, args=("lan",), daemon=True)
    first.start()
    assert entered.wait(20)
    later = threading.Thread(target=send, args=(second,), daemon=True)
    later.start()
    assert watched.found_held.wait(20)
    assert restarts == [] and answers == {}  # the second change waits for the first
    release.set()
    first.join(30)
    later.join(30)
    assert answers == {"lan": 200, second: 200}
    block = _config()["webapp"]
    if second == "stop":
        assert restarts == ["turning on Web Access", "turning off Web Access"]
        assert block["enabled"] is False
    else:

        assert (block["enabled"], block.get("public_url")) == (True, public_url)


def test_a_gateway_older_than_the_webapp_reads_as_serving_none_until_it_restarts(monkeypatch, tmp_path):
    """A gateway that predates the Webapp answers its status with "unknown verb". It serves no Webapp,
    so Web Access reports it ``off`` with a reason that names the restart (the pane then offers
    Restart gateway), never ``unavailable``, which the pane's restart wait takes as the final answer."""
    from pathlib import Path

    from hermes_cli import webapp_access, webapp_launcher

    answer = {"ok": False, "error": "unknown verb: 'webapp-status'", "protocol": 1,
              "supported_verbs": ["identify", "session-ticket", "status"]}
    monkeypatch.setattr(webapp_launcher, "_control", lambda _home, _verb, params=None: answer)
    state = webapp_access._gateway_state(Path(tmp_path))
    assert state["state"] == "off", state
    assert webapp_launcher.RESTART_COMMAND in state["reason"]
