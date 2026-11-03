# A normal failed startup, real backend and real NSIS, in a disposable CI install.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:GITHUB_REPOSITORY -cne 'rodos4312/Meu-Agent') {
    throw 'Rollback rehearsal requires a disposable Meu GitHub runner.'
}
$scratch = Join-Path $env:RUNNER_TEMP 'meu-rollback'
if (Test-Path -LiteralPath $scratch) { throw 'Rollback rehearsal requires a fresh directory.' }
$env:MEU_HOME = Join-Path $scratch 'profile'
$env:HERMES_HOME = $env:MEU_HOME
$env:MEU_AGENT_MODE = '1'
$env:HERMES_RUNTIME_DIR = Join-Path $scratch 'tools'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'
$env:PSModulePath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\Modules'
Remove-Item Env:PYTHONPATH, Env:VIRTUAL_ENV, Env:HERMES_PYTHON -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $env:MEU_HOME -Force | Out-Null
$checkout = Join-Path $env:MEU_HOME 'meu-agent'
$baseline = Join-Path $env:RUNNER_TEMP 'meu-rollback-baseline'
$candidate = Join-Path $env:GITHUB_WORKSPACE 'apps/desktop/release/meu-release-candidate'
$driver = Join-Path $PSScriptRoot 'test-meu-rollback.mjs'
& node $driver validate $baseline $candidate $scratch
if ($LASTEXITCODE -ne 0) { throw 'Rollback candidates failed verification.' }
$arguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
    (Join-Path $env:GITHUB_WORKSPACE 'scripts/install.ps1'), '-Branch', 'dev/meu-foundation',
    '-Commit', $env:GITHUB_SHA, '-HermesHome', $env:MEU_HOME, '-InstallDir', $checkout,
    '-NonInteractive', '-SkipBrowser', '-SkipComputerUse')
$quoted = ($arguments | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' '
$child = Start-Process powershell.exe -ArgumentList $quoted -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $scratch 'backend.stdout.log') `
    -RedirectStandardError (Join-Path $scratch 'backend.stderr.log')
try {
    if (-not $child.WaitForExit(1200000)) {
        & taskkill.exe /PID $child.Id /T /F | Out-Null
        throw 'Rollback backend installation timed out.'
    }
    if ($child.ExitCode -ne 0) { throw 'Rollback backend installation failed.' }
} finally { $child.Dispose() }
$launcher = Join-Path $checkout '.hermes/bin/hermes.exe'
try {
    & $launcher gateway stop
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop isolated fixture gateway.' }
    $executable = Join-Path $env:LOCALAPPDATA 'Programs/Meu/Meu.exe'
    if (Test-Path -LiteralPath $executable) { throw 'Runner already has a Meu desktop installation.' }
    $old = Get-Content -LiteralPath (Join-Path $baseline 'meu-release.json') -Raw | ConvertFrom-Json
    $child = Start-Process -FilePath (Join-Path $baseline $old.file) -ArgumentList '/S' -WindowStyle Hidden -PassThru
    try {
        if (-not $child.WaitForExit(180000) -or $child.ExitCode -ne 0) { throw 'Rollback baseline installation failed.' }
    } finally { $child.Dispose() }
    & node $driver run $baseline $candidate $scratch $executable $checkout $launcher
    if ($LASTEXITCODE -ne 0) { throw 'Automatic rollback rehearsal failed.' }
} finally {
    if (Test-Path -LiteralPath $launcher) { & $launcher gateway stop }
}
