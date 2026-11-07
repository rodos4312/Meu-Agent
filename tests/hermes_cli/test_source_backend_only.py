"""Native clients need the canonical backend, not browser/terminal renderer builds."""
from pathlib import Path
import os
import shlex
import subprocess
import sys

import pytest


def test_backend_only_avoids_node_builds_without_skipping_backend_maintenance(tmp_path, monkeypatch):
    from hermes_cli import source_build

    for name in ("ui-tui/package.json", "web/package.json", "apps/desktop/scripts/build-webapp.mjs"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    events = []
    monkeypatch.setattr("hermes_cli.main_install_repair._install_configured_features_missing_deps",
                        lambda root: events.append("features"))
    monkeypatch.setattr("hermes_cli.memory_provider_migration.migrate_all_homes", lambda: events.append("memory"))
    monkeypatch.setattr("hermes_cli.left_core_migration.migrate_all_homes", lambda: events.append("plugins"))
    monkeypatch.setattr(source_build, "source_build_env", lambda **kwargs: pytest.fail("Unused Node toolchain acquired"))
    monkeypatch.setattr(source_build, "_rebuild_served_webapp", lambda *args: pytest.fail("Unused web renderer built"))
    source_build.build_update_products(tmp_path, desktop=False, build_frontends=False)
    assert events == ["features", "memory", "plugins"]


def test_backend_completion_still_publishes_launchers_and_identity(tmp_path, monkeypatch):
    from hermes_cli.source_completion import complete_source_checkout

    events = []
    monkeypatch.setattr("hermes_cli.venv_sync.publish_launchers", lambda root: events.append("launchers"))
    monkeypatch.setattr("hermes_cli.source_build.build_update_products",
                        lambda root, **kwargs: events.append(("build", kwargs)))
    monkeypatch.setattr("hermes_cli.update_cmd_maint._run_post_update_maintenance",
                        lambda **kwargs: events.append("maintenance") or True)
    monkeypatch.setattr("hermes_cli.source_stamp.write_source_stamp", lambda root: events.append("stamp"))
    assert complete_source_checkout(tmp_path, desktop=False, assume_yes=True, backend_only=True)
    assert events == ["launchers", ("build", {"desktop": False, "build_frontends": False}), "maintenance", "stamp"]


def test_backend_flag_survives_the_bootstrap_interpreter(tmp_path, monkeypatch):
    from hermes_cli import source_completion

    entry = tmp_path / "hermes_cli/source_completion.py"
    entry.parent.mkdir()
    entry.touch()
    invoked = []
    monkeypatch.setattr(source_completion, "_bootstrap_command", lambda root, argv: invoked.append(argv) or ["prepared"])
    monkeypatch.setattr("pm.environments.activation_environment", lambda root: {})
    monkeypatch.setattr(subprocess, "call", lambda command, **kwargs: 0)
    assert source_completion.main(["--source", str(tmp_path), "--backend-only"]) == 0
    assert invoked == [["--backend-only"]]


def test_backend_flag_cannot_skip_a_requested_desktop_build(tmp_path):
    from hermes_cli.source_completion import main

    with pytest.raises(SystemExit) as error:
        main(["--source", str(tmp_path), "--backend-only", "--desktop"])
    assert error.value.code == 2


@pytest.mark.parametrize("desktop", [False, True])
def test_installer_backend_only_is_explicit_and_does_not_leave_a_desktop_stale(tmp_path, desktop, real_bash):
    root = Path(__file__).resolve().parents[2]
    checkout = tmp_path / "install"
    entry = checkout / "hermes_cli/source_completion.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("import sys; print('COMPLETION ' + repr(sys.argv[1:]))", encoding="utf-8")
    if desktop:
        (checkout / "apps/desktop/release/linux-arm64-unpacked").mkdir(parents=True)
    script = f"""
source {shlex.quote((root / 'scripts/install.sh').as_posix())} --manifest --backend-only >/dev/null
bootstrap_python() {{ boot_py={shlex.quote(Path(sys.executable).as_posix())}; }}
run_logged() {{ shift; "$@"; }}
wire_shell_path() {{ :; }}
stage_products
"""
    result = subprocess.run([real_bash, "-c", script], env={**os.environ, "HERMES_INSTALL_DIR": checkout.as_posix()},
                            text=True, capture_output=True, timeout=30, check=False)
    if desktop:
        assert result.returncode != 0
        assert "existing desktop" in result.stdout + result.stderr
        assert "COMPLETION" not in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "--backend-only" in result.stdout
