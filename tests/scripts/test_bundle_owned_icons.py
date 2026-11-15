"""The bundle compiler must receive the committed Meu favicon unchanged."""
from pathlib import Path
from types import SimpleNamespace

from scripts.bundles import stage
from scripts.bundles import payload
from scripts.build import icon_environment


def test_bundle_build_passes_owned_favicon_to_web_compiler(tmp_path, monkeypatch):
    owned_icon = b"MEU-owned-icon-fixture"
    consumed = []

    def snapshot(repo, ref, destination):
        public = destination / "web/public"
        public.mkdir(parents=True)
        (public / "favicon.ico").write_bytes(owned_icon)

    def run(command, **kwargs):
        if command[1] == "scripts/build/web.mjs":
            icons = Path(command[command.index("--icons") + 1])
            assert (icons / "web/public/favicon.ico").read_bytes() == owned_icon
            consumed.append("owned favicon")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(payload, "snapshot", snapshot)
    monkeypatch.setattr(icon_environment, "prepare_icon_environment", lambda *args: tmp_path / "python")
    monkeypatch.setattr(stage.shutil, "which", lambda name: "test-node")
    monkeypatch.setattr(stage.subprocess, "run", run)
    monkeypatch.setattr(stage, "stage_native", lambda args: 0)
    assert stage.main(["--out", str(tmp_path / "payload")]) == 0
    assert consumed == ["owned favicon"]
