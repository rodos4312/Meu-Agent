$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Disposable Windows CI only.' }
$compiler=Get-Content fixture-output/compiler.json -Raw | ConvertFrom-Json
if ($compiler.PSObject.Properties.Name -contains 'env') {
  foreach ($item in $compiler.env.PSObject.Properties) { Set-Item -LiteralPath "Env:$($item.Name)" -Value $item.Value }
}
function Run-FixtureExe([string]$Exe,[string]$Arguments,[int]$Expected) {
  $process=Start-Process -FilePath $Exe -ArgumentList $Arguments -WindowStyle Hidden -PassThru
  try {
    [void]$process.Handle
    if (-not $process.WaitForExit(30000)) { throw 'Small fixture timed out.' }
    if ($process.ExitCode -ne $Expected) { throw "Fixture exit $($process.ExitCode), expected $Expected." }
  } finally { $process.Dispose() }
}
foreach ($variant in @('baseline','fixed','fixed-full')) {
  $bootstrap=Join-Path $PWD "fixture-output/$variant-bootstrap.exe"
  $fixtureExe=Join-Path $PWD "fixture-output/$variant-uninstall.exe"
  $arguments=@('/V2',"/DBOOTSTRAP_OUT=$bootstrap","/DFIXTURE_OUT=$fixtureExe",('/DUPSTREAM_HELPER='+(Join-Path $PWD 'fixture-output/upstream-removal.nsh')),('/DMEU_HELPER='+(Join-Path $PWD 'apps/desktop/scripts/meu-long-path-uninstall.nsh')))
  if ($variant -ne 'baseline') { $arguments+='/DMEU_FIXED' }
  if ($variant -eq 'fixed-full') { $arguments+='/DFULL_UNINSTALL' }
  & $compiler.path @arguments scripts/ci/meu-rc-atomic-fixture.nsi
  if ($LASTEXITCODE -ne 0) { throw 'Fixture compilation failed.' }
  Run-FixtureExe $bootstrap '/S' 0
}
$fixtureParent=Join-Path ([IO.Path]::GetTempPath()) ('meu-atomic-fixture-'+[guid]::NewGuid().ToString('N'))
$allowed=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
if (-not [IO.Path]::GetFullPath($fixtureParent).StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture location.' }
$longRelative='resources\agent-payload\venv\Lib\site-packages\elevenlabs\text_to_speech\types\__pycache__\body_text_to_speech_streaming_with_timestamps_v_1_text_to_speech_voice_id_stream_with_timestamps_post_apply_text_normalization.cpython-314.pyc'
function New-FixtureTree([string]$Name,[bool]$Long) {
  $dir=Join-Path $fixtureParent $Name
  [IO.Directory]::CreateDirectory($dir) | Out-Null
  [IO.File]::WriteAllText((Join-Path $dir 'fixture.guard'),'owned synthetic fixture')
  [IO.File]::WriteAllText((Join-Path $dir 'a-early.txt'),'keep this exact content')
  if ($Long) {
    $file='\\?\'+(Join-Path $dir $longRelative)
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($file)) | Out-Null
    [IO.File]::WriteAllText($file,'long-file-content')
  }
  return $dir
}
$baseline=(Join-Path $PWD 'fixture-output/baseline-uninstall.exe')
$fixed=(Join-Path $PWD 'fixture-output/fixed-uninstall.exe')
$short=New-FixtureTree 'short' $false
Run-FixtureExe $baseline "/S _?=$short" 0
if (Test-Path -LiteralPath (Join-Path $short 'a-early.txt')) { throw 'Baseline short fixture did not move the file.' }
Write-Host 'PASS: original vendor algorithm handles short paths'
$original=New-FixtureTree 'original-long' $true
Run-FixtureExe $baseline "/S _?=$original" 2
if ([IO.File]::ReadAllText('\\?\'+(Join-Path $original $longRelative)) -cne 'long-file-content') { throw 'Original failure lost the long fixture.' }
Write-Host 'REPRODUCED: original vendor algorithm rejects the real long SDK filename'
$repaired=New-FixtureTree 'fixed-long' $true
Run-FixtureExe $fixed "/S _?=$repaired" 0
if ([IO.File]::Exists('\\?\'+(Join-Path $repaired $longRelative))) { throw 'Fixed algorithm left the long file behind.' }
Write-Host 'PASS: extended paths move the same long file'
$rollback=New-FixtureTree 'locked-rollback' $true
$locked=Join-Path $rollback 'zz-locked.txt'
[IO.File]::WriteAllText($locked,'locked-content')
$stream=[IO.File]::Open($locked,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read)
try {
  Run-FixtureExe $fixed "/S _?=$rollback" 2
  if ([IO.File]::ReadAllText((Join-Path $rollback 'a-early.txt')) -cne 'keep this exact content' -or [IO.File]::ReadAllText('\\?\'+(Join-Path $rollback $longRelative)) -cne 'long-file-content') { throw 'Locked-file rollback failed.' }
} finally { $stream.Dispose() }
Write-Host 'PASS: a genuinely locked file refuses replacement and restores earlier files'
Run-FixtureExe $fixed "/S _?=$rollback" 0
if (Test-Path -LiteralPath $locked) { throw 'Unlocked retry did not finish.' }
Write-Host 'PASS: retry after unlocking succeeds'
$full=New-FixtureTree 'full-uninstall' $true
Run-FixtureExe (Join-Path $PWD 'fixture-output/fixed-full-uninstall.exe') "/S _?=$full" 0
if ([IO.Directory]::Exists($full)) { throw 'Full uninstall left the fixture directory behind.' }
Write-Host 'PASS: the actual full-uninstall hook removes long paths'
@{status='passed';baselineLongPath='reproduced';fixedLongPath='passed';lockedRollback='passed';unlockedRetry='passed';fullUninstall='passed';actualRemovalHook=$true} | ConvertTo-Json | Set-Content fixture-output/result.json -Encoding utf8
