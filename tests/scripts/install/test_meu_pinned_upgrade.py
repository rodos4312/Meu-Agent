"""An installed Windows backend advances to its desktop artifact, never the branch tip."""
import os
from pathlib import Path
import subprocess

import pytest

from hermes_platform.resolver import locate_command


@pytest.mark.platforms('windows')
def test_existing_backend_updates_to_exact_pin_and_preserves_user_state(tmp_path):
    root, remote, home = (tmp_path / p for p in ('installed', 'remote', 'home'))
    remote.mkdir()
    home.mkdir()

    def git(where, *args):
        return subprocess.check_output(['git', '-C', str(where), *args], text=True).strip()
    git(remote, 'init', '-b', 'dev/meu-foundation')
    git(remote, 'config', 'user.email', 'fixture@example.invalid')
    git(remote, 'config', 'user.name', 'Fixture')
    pins = []
    for version in ('old', 'artifact', 'future'):
        (remote / 'backend.txt').write_text(version)
        git(remote, 'add', '.')
        git(remote, 'commit', '-m', version)
        pins.append(git(remote, 'rev-parse', 'HEAD'))
    subprocess.run(['git', 'clone', str(remote), str(root)], check=True, capture_output=True)
    official = 'https://github.com/rodos4312/Meu-Agent.git'
    git(root, 'remote', 'set-url', 'origin', official)
    git(root, 'config', f'url.{remote.as_uri()}.insteadOf', official)
    git(root, 'reset', '--hard', pins[0])
    state = home / 'state.db'
    state.write_bytes(b'untouched fixture state')
    installer = Path(__file__).resolve().parents[3] / 'scripts' / 'install.ps1'
    probe = tmp_path / 'upgrade.ps1'
    probe.write_text('''param($Installer,$InstallRoot,$StateHome,$Pin,[switch]$Busy)
. $Installer -InstallDir $InstallRoot -HermesHome $StateHome -Branch dev/meu-foundation -Commit $Pin
function Invoke-InstalledHermes { param([string[]]$CommandArgs)
    if (($CommandArgs -join ' ') -ne 'gateway stop') { throw 'Unexpected lifecycle command' }
    if ($Busy) { throw 'fixture active work: stop refused' }
}
Update-MeuPinnedCheckout
''', encoding='utf-8')
    shell = locate_command('powershell')
    assert shell.found

    def upgrade(pin, busy=False):
        return subprocess.run([*shell.command, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(probe), '-Installer', str(installer), '-InstallRoot', str(root),
            '-StateHome', str(home), '-Pin', pin, *(['-Busy'] if busy else [])],
            capture_output=True, text=True, timeout=90, check=False,
            env=dict(os.environ, HERMES_HOME=str(home), MEU_AGENT_MODE='1'))
    result = upgrade(pins[1])
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(root, 'rev-parse', 'HEAD') == pins[1]  # remote has a newer, untested tip
    assert git(root, 'branch', '--show-current') == 'dev/meu-foundation'
    assert state.read_bytes() == b'untouched fixture state'
    assert upgrade(pins[0]).returncode == 0  # older installer never downgrades
    assert git(root, 'rev-parse', 'HEAD') == pins[1]
    assert upgrade(pins[2], busy=True).returncode != 0
    assert git(root, 'rev-parse', 'HEAD') == pins[1]
    (root / 'backend.txt').write_text('local changes')
    assert upgrade(pins[2]).returncode != 0
    assert (root / 'backend.txt').read_text() == 'local changes'
    assert state.read_bytes() == b'untouched fixture state'
