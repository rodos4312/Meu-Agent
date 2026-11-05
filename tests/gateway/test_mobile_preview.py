"""Exercise Desktop enrolment, TLS pairing and one canonical phone turn."""

import asyncio
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

from tests.gateway.fixtures.local_recovery_probe import Model, child_env, daemon, rpc, websocket
from tests.gateway.test_native_http_auth import headers, ticket


def _unpack(code):
    version, *fields = code.split(".")
    assert version == "meu2"
    origin, challenge, cert = [base64.urlsafe_b64decode(field + "=" * (-len(field) % 4)) for field in fields]
    tls = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
    return origin.decode(), challenge.decode(), tls


async def _desktop_session(home, desc, session_id=None):
    async with websocket(home, desc) as socket:
        if session_id is None:
            result = await rpc(socket, "session.create", source="gui", request_id="desktop-only", toolsets=[])
            return result["result"]["session_id"]
        opened = await rpc(socket, "session.resume", session_id=session_id, display_projection=True)
        assert opened["result"]["session_id"] == session_id, opened
        messages = opened["result"]["display_messages"]
        assert any(row.get("text") == "RECOVERY_ACK_Γεια σου Meu" for row in messages)
        submitted = await rpc(socket, "prompt.submit", session_id=session_id, input_id="desktop-follow-up",
                              text="Συνέχεια από Windows")
        admission = submitted["result"]["admission_id"]
        async with asyncio.timeout(30):
            while True:
                reply = await rpc(socket, "prompt.receipt", session_id=session_id, admission_id=admission)
                if reply["result"]["status"] == "terminal":
                    assert reply["result"]["outcome"] == "completed"
                    return session_id
                await asyncio.sleep(.1)


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
            foreign = asyncio.run(_desktop_session(home, desc))
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
                assert phone.get("/meu/sessions").json() == {"sessions": []}
                assert phone.get(f"/meu/sessions/{foreign}").status_code == 404
                creation_key = str(uuid.uuid4())
                created = phone.post("/meu/sessions", json={}, headers={"Idempotency-Key": creation_key})
                assert created.status_code == 201, created.text
                session_id = created.json()["id"]
                replay = phone.post("/meu/sessions", json={}, headers={"Idempotency-Key": creation_key})
                assert replay.json()["id"] == session_id
                assert phone.get("/meu/sessions").json()["sessions"][0]["id"] == session_id
                assert phone.get(f"/meu/sessions/{session_id}").json()["messages"] == []
                key = str(uuid.uuid4())
                body = {"input": "Γεια σου Meu", "session_id": session_id}
                assert phone.post("/v1/runs", json={**body, "session_id": foreign},
                                  headers={"Idempotency-Key": key}).status_code == 404
                run = phone.post("/v1/runs", json=body, headers={"Idempotency-Key": key})
                assert run.status_code == 202, (run.text, (home / "first.log").read_text(errors="replace"))
                same = phone.post("/v1/runs", json=body, headers={"Idempotency-Key": key})
                assert same.status_code == 202 and same.json() == run.json()
                collision = phone.post("/v1/runs", json={**body, "input": "different"},
                                       headers={"Idempotency-Key": key})
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
                sidebar = desktop.get("/api/sessions?min_messages=1&exclude_sources=cron", headers=owner())
                assert sidebar.status_code == 200, sidebar.text
                assert session_id in {row["id"] for row in sidebar.json()["sessions"]}
                assert asyncio.run(_desktop_session(home, desc, session_id)) == session_id
                assert len(peer.requests) == 2
                messages = phone.get(f"/meu/sessions/{session_id}").json()["messages"]
                assert [row["content"] for row in messages][-2:] == [
                    "Συνέχεια από Windows", "RECOVERY_ACK_Συνέχεια από Windows"]
                assert desktop.delete(path, headers=owner()).json()["state"] == "off"
                with pytest.raises(httpx.TransportError):
                    phone.get("/v1/capabilities")
            restarted = desktop.post(path, headers=owner())
            origin, challenge, tls = _unpack(restarted.json()["code"])
            with httpx.Client(base_url=origin, verify=tls, trust_env=False) as phone:
                new_key = phone.post("/meu/pair", json={"challenge": challenge}).json()["key"]
                phone.headers["Authorization"] = "Bearer " + new_key
                assert phone.get("/meu/sessions").json()["sessions"][0]["id"] == session_id
                assert phone.get(f"/meu/sessions/{session_id}").json()["messages"] == messages
    finally:
        peer.shutdown()
        peer.server_close()
