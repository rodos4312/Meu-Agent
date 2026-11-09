"""Exercise Desktop enrolment, TLS pairing and one canonical phone turn."""

import asyncio
import base64
from http.server import ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import threading
import time
from types import SimpleNamespace
import uuid

import httpx
import pytest

from tests.gateway.fixtures.local_recovery_probe import Model, child_env, daemon, rpc, websocket
from tests.gateway.test_native_http_auth import headers, ticket


class _WeatherModel(Model):
    def reply(self, text, messages):
        if text != "MOBILE_WEB_TEST":
            return super().reply(text, messages)
        if messages[-1]["role"] == "tool":
            return {"role": "assistant", "content": messages[-1]["content"]}, "stop"
        return {"role": "assistant", "tool_calls": [{
            "id": "call_web", "index": 0, "type": "function",
            "function": {"name": "web_extract", "arguments": '{"urls":["https://example.com/mobile-weather"]}'},
        }]}, "tool_calls"


def _wait_for_run(phone, run_id):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        result = phone.get(f"/v1/runs/{run_id}").json()
        if result["status"] not in {"queued", "started"}:
            return result
        time.sleep(.1)
    pytest.fail("The mobile turn did not finish")


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


def test_tailscale_network_uses_only_the_vpn_adapter(monkeypatch):
    import psutil

    from gateway.mobile_preview import tailscale_network

    adapters = {"Ethernet": [SimpleNamespace(family=socket.AF_INET, address="100.91.4.20")]}
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: adapters)
    with pytest.raises(ValueError, match="Connect Tailscale"):
        tailscale_network()
    adapters["Tailscale"] = [
        SimpleNamespace(family=socket.AF_INET6, address="fd7a:115c:a1e0::10"),
        SimpleNamespace(family=socket.AF_INET, address="100.101.2.10", netmask="255.255.255.255"),
    ]
    interface = tailscale_network()
    assert interface.ip == ipaddress.IPv4Address("100.101.2.10")
    assert ipaddress.IPv4Address("100.120.8.44") in interface.network
    assert ipaddress.IPv4Address("192.168.1.2") not in interface.network


def test_phone_tools_follow_the_profiles_web_setting():
    from gateway.session_policy import MOBILE_SESSION_PREFIX, _resolve_toolsets

    request = {"request_id": MOBILE_SESSION_PREFIX + "example", "toolsets": []}
    enabled = {"platform_toolsets": {"cli": ["web", "terminal", "file"]}}
    assert _resolve_toolsets(request, enabled, "gui", False) == {"web"}
    enabled["agent"] = {"disabled_toolsets": ["web"]}
    assert _resolve_toolsets(request, enabled, "gui", False) == set()


@pytest.mark.parametrize("remote", [False, True], ids=["lan", "tailscale"])
def test_mobile_preview_pairs_and_executes_one_owned_turn(tmp_path, remote):
    root = Path(__file__).resolve().parents[2]
    home, user = tmp_path / "state", tmp_path / "user"
    home.mkdir()
    user.mkdir()
    peer = ThreadingHTTPServer(("127.0.0.1", 0), _WeatherModel)
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
               FIRECRAWL_API_KEY="test-only-no-live-calls",
               HERMES_DASHBOARD_SESSION_TOKEN="normal-http-owner", PYTHONUNBUFFERED="1")
    path = "/api/mobile-preview"
    start_path = f"{path}/tailscale" if remote else path
    try:
        with daemon(root, home, env, barrier=True, fixture="mobile_preview_daemon.py") as (_, desc), \
                httpx.Client(base_url=desc["api_origin"], trust_env=False, timeout=30) as desktop:
            def owner():
                return headers(ticket(home, desc))

            assert desktop.post(start_path, headers={"Authorization": "Bearer normal-http-owner"}).status_code == 403
            foreign = asyncio.run(_desktop_session(home, desc))
            started = desktop.post(start_path, headers=owner())
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
                connected = desktop.get(path, headers=owner()).json()
                assert connected["state"] == "paired"
                assert connected["code"] is None
                assert (connected["seconds"] > 3600) == remote
                other_path = path if remote else f"{path}/tailscale"
                assert desktop.post(other_path, headers=owner()).status_code == 409
                phone.headers["Authorization"] = "Bearer " + paired.json()["key"]
                shared = home / "phone-files"
                shared.mkdir()
                selected = desktop.post("/api/meu-transfers/folder", headers=owner(), json={"directory": str(shared)})
                assert selected.status_code == 200, selected.text
                listing = phone.get("/api/meu-transfers")
                assert listing.status_code == 200, listing.text
                generation = listing.json()["root_id"]
                parameters = {"name": "phone-document.bin", "root_id": generation}
                phone_bytes = bytes(range(256)) * 8193  # beyond the old 2 MiB JSON ceiling
                sent = phone.post("/api/meu-transfers/upload", params=parameters, content=phone_bytes)
                assert sent.status_code == 200, sent.text
                assert (shared / parameters["name"]).read_bytes() == phone_bytes
                assert phone.post("/api/meu-transfers/upload", params=parameters, content=b"replacement").status_code == 409
                assert (shared / parameters["name"]).read_bytes() == phone_bytes
                assert phone.get("/api/meu-transfers/download", params=parameters).content == phone_bytes
                (shared / "from-pc.txt").write_bytes("Από το PC στο κινητό".encode())
                assert phone.get("/api/meu-transfers/download", params={"name": "from-pc.txt", "root_id": generation}).content == (shared / "from-pc.txt").read_bytes()
                assert phone.get("/api/meu-transfers/download", params={"name": "../config.yaml", "root_id": generation}).status_code == 400
                (shared / "Έργο κινητού").mkdir()
                subfolder = {"path": "Έργο κινητού", "root_id": generation}
                nested = phone.get("/api/meu-transfers", params=subfolder)
                assert nested.status_code == 200, nested.text
                nested_parameters = {**subfolder, "directory_id": nested.json()["directory_id"], "name": "phone-document.bin"}
                assert phone.post("/api/meu-transfers/upload", params=nested_parameters, content=b"separate project").status_code == 200
                assert phone.get("/api/meu-transfers/download", params=nested_parameters).content == b"separate project"
                assert (shared / "Έργο κινητού" / "phone-document.bin").read_bytes() == b"separate project"
                assert (shared / "phone-document.bin").read_bytes() == phone_bytes
                assert desktop.post("/api/meu-transfers/folder", headers=owner(), json={"directory": ""}).status_code == 200
                assert phone.get("/api/meu-transfers/download", params=parameters).status_code == 409
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
                another = phone.post("/meu/sessions", json={}, headers={"Idempotency-Key": str(uuid.uuid4())})
                assert another.status_code == 201, another.text
                another_id = another.json()["id"]
                assert another_id != session_id
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
                result = _wait_for_run(phone, run.json()["run_id"])
                assert result["status"] == "completed", result
                assert result["output"] == "RECOVERY_ACK_Γεια σου Meu"
                assert len(peer.requests) == 1
                assert {tool["function"]["name"] for tool in peer.requests[0].get("tools", [])} == {
                    "web_search", "web_extract",
                }
                assert phone.get("/v1/runs/run_foreign").status_code == 404
                sidebar = desktop.get("/api/sessions?min_messages=1&exclude_sources=cron", headers=owner())
                assert sidebar.status_code == 200, sidebar.text
                assert session_id in {row["id"] for row in sidebar.json()["sessions"]}
                session_path = f"/meu/sessions/{session_id}"
                before = phone.get(session_path).json()
                since = {"since": before["revision"]}
                assert phone.get(session_path, params=since).json() == {"unchanged": True}
                assert asyncio.run(_desktop_session(home, desc, session_id)) == session_id
                assert len(peer.requests) == 2
                updated = phone.get(session_path, params=since).json()
                assert updated["revision"] != before["revision"]
                assert phone.get(session_path, params={"since": updated["revision"]}).json() == {"unchanged": True}
                messages = updated["messages"]
                assert [row["content"] for row in messages][-2:] == [
                    "Συνέχεια από Windows", "RECOVERY_ACK_Συνέχεια από Windows"]
                assert phone.get(f"/meu/sessions/{another_id}").json()["messages"] == []
                weather = phone.post("/v1/runs", json={"input": "MOBILE_WEB_TEST", "session_id": another_id},
                                     headers={"Idempotency-Key": str(uuid.uuid4())})
                assert weather.status_code == 202
                result = _wait_for_run(phone, weather.json()["run_id"])
                assert result["status"] == "completed"
                assert "fixture forecast" in result["output"]
                assert desktop.delete(path, headers=owner()).json()["state"] == "off"
                with pytest.raises(httpx.TransportError):
                    phone.get("/v1/capabilities")
            restarted = desktop.post(start_path, headers=owner())
            origin, challenge, tls = _unpack(restarted.json()["code"])
            with httpx.Client(base_url=origin, verify=tls, trust_env=False) as phone:
                new_key = phone.post("/meu/pair", json={"challenge": challenge}).json()["key"]
                phone.headers["Authorization"] = "Bearer " + new_key
                assert {row["id"] for row in phone.get("/meu/sessions").json()["sessions"]} == {
                    session_id, another_id}
                assert phone.get(f"/meu/sessions/{session_id}").json()["messages"] == messages
    finally:
        peer.shutdown()
        peer.server_close()
