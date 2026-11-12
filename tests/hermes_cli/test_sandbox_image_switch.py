"""The default sandbox image change is a decision, not a surprise.

Two contracts, exercised through the real config loader, both env bridges and the module the CLI
startup offer and the Screen pane call:

* ``TERMINAL_DOCKER_IMAGE_PINNED`` tells the runtime whether ``docker_image`` is the user's
  choice (config.yaml key, or TERMINAL_DOCKER_IMAGE set before any bridge) or the shipped
  default — for the launch-profile bridge and for a routed profile's terminal scope alike.
* ``sandbox_image_switch``: a pending switch exists only for docker + unpinned + a labeled
  container on another image; approve pins the target, keep pins the current image, and either
  answer ends the offer. A fake ``docker`` binary on PATH stands in for the daemon.
"""

import os
import stat
from pathlib import Path
import pytest
import hermes_yaml as yaml


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / ".hermes"
    h.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(h))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in ("TERMINAL_ENV", "TERMINAL_DOCKER_IMAGE", "TERMINAL_DOCKER_IMAGE_PINNED"):
        monkeypatch.delenv(var, raising=False)
    return h


def _write(home: Path, terminal: dict) -> None:
    (home / "config.yaml").write_text(yaml.safe_dump({"terminal": terminal}), encoding="utf-8")


# ── pin verdict, launch-profile bridge ──────────────────────────────────────────────────────────

def test_bridge_marks_default_image_unpinned_and_file_key_pinned(home):
    from hermes_cli.config import apply_terminal_config_to_env
    from hermes_cli.config_defaults import DEFAULT_SANDBOX_IMAGE

    _write(home, {"backend": "docker"})
    env = apply_terminal_config_to_env(env={})
    assert env["TERMINAL_DOCKER_IMAGE"] == DEFAULT_SANDBOX_IMAGE
    assert env["TERMINAL_DOCKER_IMAGE_PINNED"] == "0"

    # Pinning to the value that EQUALS the default is still a pin: the approval writes exactly this.
    _write(home, {"backend": "docker", "docker_image": DEFAULT_SANDBOX_IMAGE})
    env = apply_terminal_config_to_env(env={}, override=True)
    assert env["TERMINAL_DOCKER_IMAGE_PINNED"] == "1"


def test_bridge_treats_a_preset_env_image_as_pinned_and_keeps_a_launcher_verdict(home):
    from hermes_cli.config import apply_terminal_config_to_env

    _write(home, {"backend": "docker"})
    env = apply_terminal_config_to_env(env={"TERMINAL_DOCKER_IMAGE": "ghcr.io/me/mine:1"})
    assert env["TERMINAL_DOCKER_IMAGE_PINNED"] == "1", "an operator's env var is their choice"

    # A child inherits the launcher's bridged image AND its verdict; the child bridge keeps it.
    env = apply_terminal_config_to_env(env={"TERMINAL_DOCKER_IMAGE": "whatever", "TERMINAL_DOCKER_IMAGE_PINNED": "0"})
    assert env["TERMINAL_DOCKER_IMAGE_PINNED"] == "0"


# ── pin verdict, routed profile scope ───────────────────────────────────────────────────────────

def test_terminal_scope_recomputes_the_pin_per_profile(home, tmp_path):
    from tools.terminal_scope import build_profile_terminal_scope
    from hermes_cli.config_defaults import DEFAULT_SANDBOX_IMAGE

    _write(home, {"backend": "docker"})
    scope = build_profile_terminal_scope(home, env_overlay={"TERMINAL_DOCKER_IMAGE_PINNED": "1"})
    assert scope["TERMINAL_DOCKER_IMAGE"] == DEFAULT_SANDBOX_IMAGE
    assert scope["TERMINAL_DOCKER_IMAGE_PINNED"] == "0", "the launch overlay's verdict is never inherited"

    other = tmp_path / "profiles" / "b"
    other.mkdir(parents=True)
    _write(other, {"backend": "docker", "docker_image": "ghcr.io/me/mine:1"})
    scope = build_profile_terminal_scope(other)
    assert scope["TERMINAL_DOCKER_IMAGE_PINNED"] == "1"

    (other / ".env").write_text("TERMINAL_DOCKER_IMAGE=ghcr.io/me/env:2\n", encoding="utf-8")
    _write(other, {"backend": "docker"})
    assert build_profile_terminal_scope(other)["TERMINAL_DOCKER_IMAGE_PINNED"] == "1"


# ── the switch module against a fake docker ─────────────────────────────────────────────────────

def test_terminal_scope_pins_an_image_written_in_the_profile_env_even_when_it_spells_the_default(home):
    """Provenance, not value: the approval writes the default's exact tag, and a profile whose .env carries
    TERMINAL_DOCKER_IMAGE chose it. The scope must agree with the bridge's verdict for the same input."""
    from tools.terminal_scope import build_profile_terminal_scope
    from hermes_cli.config_defaults import DEFAULT_SANDBOX_IMAGE

    _write(home, {"backend": "docker"})
    (home / ".env").write_text(f"TERMINAL_DOCKER_IMAGE={DEFAULT_SANDBOX_IMAGE}\n", encoding="utf-8")
    scope = build_profile_terminal_scope(home)
    assert scope["TERMINAL_DOCKER_IMAGE"] == DEFAULT_SANDBOX_IMAGE
    assert scope["TERMINAL_DOCKER_IMAGE_PINNED"] == "1"

    (home / ".env").write_text("TERMINAL_DOCKER_IMAGE=ghcr.io/me/mine:1\n", encoding="utf-8")
    assert build_profile_terminal_scope(home)["TERMINAL_DOCKER_IMAGE_PINNED"] == "1"
    (home / ".env").write_text("OTHER=1\n", encoding="utf-8")
    assert build_profile_terminal_scope(home)["TERMINAL_DOCKER_IMAGE_PINNED"] == "0"

def _fake_docker(tmp_path, monkeypatch, ps_output: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / "docker"
    exe.write_text("#!/bin/sh\n"
                   "case \"$1\" in ps) printf '%s' \"$PS_OUTPUT\";; *) exit 0;; esac\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PS_OUTPUT", ps_output)
    from tools.environments import docker as docker_env
    monkeypatch.setattr(docker_env, "_docker_executable", None)
    return exe

