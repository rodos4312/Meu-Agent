# Install a signed rehearsal baseline only on a fresh, disposable Windows runner.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:GITHUB_REPOSITORY -cne 'rodos4312/Meu-Agent') {
  throw 'Native upgrade rehearsal is restricted to a disposable Meu GitHub runner.'
}
$scratch = [IO.Path]::GetFullPath((Join-Path $env:RUNNER_TEMP 'meu-native-upgrade'))
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
$baseline = Join-Path $env:RUNNER_TEMP 'meu-baseline-candidate'
$candidate = Join-Path $env:RUNNER_TEMP 'meu-target-candidate'
$driver = Join-Path $PSScriptRoot 'test-meu-native-upgrade.mjs'
& node $driver validate $baseline $candidate $scratch
if ($LASTEXITCODE -ne 0) { throw 'Candidate signature/hash validation failed before installation.' }
$old = Get-Content -LiteralPath (Join-Path $baseline 'meu-release.json') -Raw | ConvertFrom-Json
if ($old.version -cne '0.1.0-dev.20' -or $old.commit -cne '839c47fbb8abd9287002ec4b35ce009c492c2442') {
  throw 'The baseline does not match the pinned public Meu dev.20 release.'
}
$executable = Join-Path $env:LOCALAPPDATA 'Programs\Meu\Meu.exe'
if (Test-Path -LiteralPath $executable) { throw 'Rehearsal requires a fresh runner without an existing Meu installation.' }
$installer = Start-Process -FilePath (Join-Path $baseline $old.file) -ArgumentList '/S' -WindowStyle Hidden -PassThru
try {
  if (-not $installer.WaitForExit(180000)) { throw 'Baseline installation exceeded 180 seconds.' }
  if ($installer.ExitCode -ne 0) { throw "Baseline installer exited $($installer.ExitCode)." }
} finally { $installer.Dispose() }
if (-not (Test-Path -LiteralPath $executable)) { throw 'Baseline Meu executable is missing.' }
& node $driver run $baseline $candidate $scratch $executable
if ($LASTEXITCODE -ne 0) { throw 'Real native update rehearsal failed.' }
