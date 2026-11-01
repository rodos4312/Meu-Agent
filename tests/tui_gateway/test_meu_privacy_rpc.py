"""Legacy Desktop RPC callers cannot opt a Meu profile into shared metrics."""

import hermes_yaml as yaml

from tui_gateway import server


def test_rpc_refuses_opt_in_and_persists_only_in_the_requested_profile(tmp_path, monkeypatch):
    launch, worker = tmp_path / "launch", tmp_path / "profiles" / "work"
    for home in (launch, worker):
        home.mkdir(parents=True)
        (home / "config.yaml").write_text(yaml.safe_dump({"model": {"provider": "deepseek"}}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setattr(server, "_hermes_home", launch)
    monkeypatch.setattr(server, "_profile_home", lambda name: worker if name == "work" else None)
    server._cfg_cache = server._cfg_sig = server._cfg_path = None
    before = (launch / "config.yaml").read_bytes()
    response = server._methods["shared_metrics.set"]("rid", {
        "profile": "work", "enabled": True, "send": True, "first_run": True,
    })
    assert response["result"] == {"enabled": False, "send": False, "decided": True, "reask": False}
    raw = yaml.safe_load((worker / "config.yaml").read_text(encoding="utf-8"))
    assert raw["telemetry"]["shared_metrics"]["enabled"] is False
    assert raw["telemetry"]["shared_metrics"]["send"] is False
    assert raw["model"]["provider"] == "deepseek"
    assert (launch / "config.yaml").read_bytes() == before
    assert not (launch / "telemetry").exists()
    assert server._methods["shared_metrics.status"]("rid", {"profile": "work"})["result"] == response["result"]
