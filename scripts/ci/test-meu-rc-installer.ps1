$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Disposable GitHub runner only.' }
function Run-Installer([string]$Exe) {
    $child = Start-Process -FilePath $Exe -ArgumentList '/S' -WindowStyle Hidden -PassThru
    try {
        if (-not $child.WaitForExit(600000)) { throw 'Installer timed out.' }
        if ($child.ExitCode -ne 0) { throw "Installer failed: $($child.ExitCode)" }
    } finally { $child.Dispose() }
}
$installer = @(Get-ChildItem apps/desktop/release/Meu-*-win-x64.exe -File)
if ($installer.Count -ne 1) { throw 'Expected one installer.' }
Run-Installer $installer[0].FullName
$exe = Join-Path $env:LOCALAPPDATA 'Programs/Meu/Meu.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Installed Meu.exe missing.' }
$info = (Get-Item -LiteralPath $exe).VersionInfo
if ($info.ProductName -cne 'Meu') { throw 'Incorrect executable branding.' }
$scratch = Join-Path $env:RUNNER_TEMP 'meu-rc-installed-smoke'
node scripts/ci/meu-rc-desktop-smoke.mjs $exe $scratch $env:GITHUB_SHA
if ($LASTEXITCODE -ne 0) { throw 'Installed real-runtime smoke failed.' }
$proof = Join-Path $scratch 'profile/.meu-rc-repair-proof'
$value = [guid]::NewGuid().ToString('N')
[IO.File]::WriteAllText($proof,$value)
Run-Installer $installer[0].FullName
if ([IO.File]::ReadAllText($proof) -cne $value) { throw 'Repair changed the test profile.' }
Write-Host 'PASS: actual installer and repair with preserved isolated profile'
