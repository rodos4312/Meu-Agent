"""Exercise Desktop enrolment, TLS pairing and one canonical phone turn."""

import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import threading
import time
import uuid

import httpx
import pytest

from tests.gateway.fixtures.local_recovery_probe import Model, child_env, daemon
from tests.gateway.test_native_http_auth import headers, ticket


def _unpack(code):
    version, *fields = code.split(".")
    assert version == "meu2"
    origin, challenge, cert = [base64.urlsafe_b64decode(field + "=" * (-len(field) % 4)) for field in fields]
    tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
    return origin.decode(), challenge.decode(), tls


def test_mobile_preview_pairs_and_executes_one_owned_turn(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home, user = tmp_path / "state", tmp_path / "user"
    home.mkdir()
    user.mkdir()
    peer = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    peer.requests = []
    threading.Thread(target=peer.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{peer.server_port}/v1"
    (home / "config.yaml").write_text(json.dumps({
        "model": {"provider": "custom", "default": "local-wire-stub", "base_url": base},
        "gateway": {"multiplex_profiles": False},
        "auxiliary": {"title_generation": {"enabled": False}},
        "terminal": {"cwd": str(home)},
    }))
    env = dict(child_env(), HOME=str(user), USERPROFILE=str(user), HERMES_HOME=str(home),
               PYTHONPATH=str(root), OPENAI_API_KEY="loopback-only", OPENAI_BASE_URL=base,
               HERMES_DASHBOARD_SESSION_TOKEN="normal-http-owner", PYTHONUNBUFFERED="1")
    path = "/api/mobile-preview"
    try:
        with daemon(root, home, env, barrier=True, fixture="mobile_preview_daemon.py") as (_, desc), \
                httpx.Client(base_url=desc["api_origin"], trust_env=False) as desktop:
            def owner():
                return headers(ticket(home, desc))

            assert desktop.post(path, headers={"Authorization": "Bearer normal-http-owner"}).status_code == 403
            started = desktop.post(path, headers=owner())
            assert started.status_code == 200, started.text
            assert started.json()["state"] == "waiting"
            origin, challenge, tls = _unpack(started.json()["code"])
            with httpx.Client(base_url=origin, verify=tls, trust_env=False) as phone:
                assert phone.get("/v1/capabilities").status_code == 401
                assert phone.post("/meu/pair", json={"challenge": "wrong"}).status_code == 401
                assert phone.post("/meu/pair", json={"challenge": challenge},
                                  headers={"Origin": "https://unrelated.test"}).status_code == 403
                paired = phone.post("/meu/pair", json={"challenge": challenge})
                assert paired.status_code == 200, paired.text
                assert phone.post("/meu/pair", json={"challenge": challenge}).status_code == 401
                assert desktop.get(path, headers=owner()).json()["state"] == "paired"
                assert desktop.get(path, headers=owner()).json()["code"] is None
                phone.headers["Authorization"] = "Bearer " + paired.json()["key"]
                assert phone.get("/v1/capabilities").status_code == 200
                assert phone.get("/api/sessions").status_code == 404
                key = str(uuid.uuid4())
                body = {"input": "Γεια σου Meu", "session_id": "untrusted-client-session"}
                run = phone.post("/v1/runs", json=body, headers={"Idempotency-Key": key})
                assert run.status_code == 202, (run.text, (home / "first.log").read_text(errors="replace"))
                same = phone.post("/v1/runs", json=body, headers={"Idempotency-Key": key})
                assert same.status_code == 202 and same.json() == run.json()
                collision = phone.post("/v1/runs", json={"input": "different"}, headers={"Idempotency-Key": key})
                assert collision.status_code == 409
                run_id = run.json()["run_id"]
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    result = phone.get(f"/v1/runs/{run_id}").json()
                    if result["status"] not in {"queued", "started"}:
                        break
                    time.sleep(.1)
                assert result["status"] == "completed", result
                assert result["output"] == "RECOVERY_ACK_Γεια σου Meu"
                assert len(peer.requests) == 1
                assert not peer.requests[0].get("tools")
                assert phone.get("/v1/runs/run_foreign").status_code == 404
                assert desktop.delete(path, headers=owner()).json()["state"] == "off"
                with pytest.raises(httpx.TransportError):
                    phone.get("/v1/capabilities")
    finally:
        peer.shutdown()
        peer.server_close()
