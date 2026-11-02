"""The Windows bootstrap cannot leave installation usage receipts, even on failure."""

import os
from pathlib import Path
import subprocess

import pytest

from hermes_platform.resolver import locate_command


@pytest.mark.platforms("windows")
def test_installer_receipt_helpers_create_no_telemetry_files(tmp_path):
    installer = Path(__file__).resolve().parents[3] / "scripts" / "install.ps1"
    shell = locate_command("powershell")
    assert shell.found
    probe = tmp_path / "probe.ps1"
    probe.write_text(
        'param([string]$Installer, [string]$ProbeHome)\n'
        '. $Installer -HermesHome $ProbeHome\n'
        'Write-InstallReceipt success none none\n'
        'Write-InstallReceipt failed repository other\n', encoding="utf-8",
    )
    home = tmp_path / "home"
    # Cold Windows CI has exceeded 30s while starting PowerShell/loading this
    # script. Keep a bounded startup allowance; the receipt assertions decide
    # correctness, not shell startup latency on a busy runner.
    result = subprocess.run([
        *shell.command, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe),
        "-Installer", str(installer), "-ProbeHome", str(home),
    ], capture_output=True, text=True, timeout=90, check=False, env=dict(os.environ, HERMES_HOME=str(home)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / "telemetry").exists()
