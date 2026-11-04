# Real pinned installer and canonical gateway, only in a disposable Meu CI runner.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:GITHUB_REPOSITORY -cne 'rodos4312/Meu-Agent') {
    throw 'Backend rehearsal requires a disposable Meu GitHub runner.'
}
$target = $env:GITHUB_SHA
if ($target -cnotmatch '^[a-f0-9]{40}$') { throw 'Missing target commit.' }
$baseline = '78575c51ed6c598bf5c432955706f803cb657e5d'
$scratch = Join-Path $env:RUNNER_TEMP 'meu-backend-upgrade'
$profile = Join-Path $scratch 'profile'
$checkout = Join-Path $scratch 'source'
if (Test-Path -LiteralPath $scratch) { throw 'Backend rehearsal requires a fresh directory.' }
New-Item -ItemType Directory -Path $profile -Force | Out-Null
$env:MEU_AGENT_MODE = '1'
$env:MEU_HOME = $profile
$env:HERMES_HOME = $profile
$env:HERMES_RUNTIME_DIR = Join-Path $scratch 'tools'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'
# GitHub runs this driver under PowerShell 7, but desktop bootstrap uses 5.1.
# Do not pass PS7's module directories to that child (Get-FileHash can disappear).
$env:PSModulePath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\Modules'
# Inherited setup-pm paths must not select the CI checkout as the installed runtime.
Remove-Item Env:PYTHONPATH, Env:VIRTUAL_ENV, Env:HERMES_PYTHON -ErrorAction SilentlyContinue
$installer = Join-Path $env:GITHUB_WORKSPACE 'scripts/install.ps1'
$files = @{
    '.env' = "DEEPSEEK_API_KEY=meu-ci-not-a-real-key`n"
    'memories/MEMORY.md' = "Preserve this backend rehearsal memory.`n"
    'skills/rehearsal/SKILL.md' = "---`nname: rehearsal`ndescription: CI fixture`n---`nPreserve this skill.`n"
}
foreach ($name in $files.Keys) {
    $destination = Join-Path $profile $name
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    [IO.File]::WriteAllText($destination, $files[$name])
}

function Install-Pin([string]$Pin, [string]$Label) {
    # Same complete ladder used by desktop bootstrap; optional browser/driver downloads
    # are omitted in this fixture only. No implementation or gateway mock is installed.
    $arguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $installer,
        '-Branch', 'dev/meu-foundation', '-Commit', $Pin, '-HermesHome', $profile,
        '-InstallDir', $checkout, '-NonInteractive', '-SkipBrowser', '-SkipComputerUse')
    $quoted = ($arguments | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' '
    $child = Start-Process powershell.exe -ArgumentList $quoted -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $scratch "$Label.stdout.log") `
        -RedirectStandardError (Join-Path $scratch "$Label.stderr.log")
    try {
        if (-not $child.WaitForExit(1200000)) {
            & taskkill.exe /PID $child.Id /T /F | Out-Null
            throw "Installer timed out during $Label."
        }
        if ($child.ExitCode -ne 0) { throw "Installer failed during $Label (exit $($child.ExitCode)); see installer logs." }
    } finally { $child.Dispose() }
    $actual = (& git -C $checkout rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -cne $Pin) { throw 'Installed checkout differs from requested pin.' }
    $marker = Get-Content -LiteralPath (Join-Path $checkout '.hermes-bootstrap-complete') -Raw | ConvertFrom-Json
    if ($marker.pinnedCommit -cne $Pin) { throw 'Bootstrap marker differs from installed checkout.' }
}

function Assert-Gateway([string]$Pin) {
    $launcher = Join-Path $checkout '.hermes/bin/hermes.exe'
    if (-not (Test-Path -LiteralPath $launcher)) { throw 'Installed native launcher is missing.' }
    $answer = & $launcher gateway ensure --json --timeout 90
    if ($LASTEXITCODE -ne 0) { throw 'Installed gateway did not become ready.' }
    $state = $answer | ConvertFrom-Json
    if ($state.state -cne 'ready' -or $state.client_code_sha -cne $Pin -or $state.endpoint.code_sha -cne $Pin) {
        throw 'Client or live gateway is running the wrong source revision.'
    }
    Write-Host "[PASS] Real installed gateway is ready at $Pin"
}

try {
    Install-Pin $baseline 'baseline'
    Assert-Gateway $baseline
    Install-Pin $target 'upgrade'
    Assert-Gateway $target
    foreach ($name in $files.Keys) {
        if ([IO.File]::ReadAllText((Join-Path $profile $name)) -cne $files[$name]) { throw "Profile changed: $name" }
    }
    @{ from = $baseline; to = $target; realInstaller = $true; realGateway = $true;
       publicDesktopFeed = $false; preserved = @('API-key fixture', 'memory', 'skill') } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $scratch 'result.json') -Encoding utf8
    Write-Host '[PASS] Pinned backend upgraded and its canonical gateway restarted; fixture data survived.'
} finally {
    $launcher = Join-Path $checkout '.hermes/bin/hermes.exe'
    if (Test-Path -LiteralPath $launcher) { & $launcher gateway stop }
}
