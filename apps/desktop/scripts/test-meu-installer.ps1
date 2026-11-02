# Smoke-check the unsigned Meu development installer on an ephemeral Windows CI runner.
# Launches the installed renderer with an isolated fake backend and no model/API credentials.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This install/uninstall rehearsal runs only on a disposable GitHub runner.' }

function Invoke-SmokeProcess([string]$Executable, [string]$Arguments) {
  $child = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru
  try {
    if (-not $child.WaitForExit(180000)) {
      Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue
      throw 'Installer lifecycle step exceeded 180 seconds.'
    }
    if ($child.ExitCode -ne 0) { throw "Installer lifecycle exit code: $($child.ExitCode)" }
  } finally { $child.Dispose() }
}

$release = Join-Path $PSScriptRoot '..\release'
$installer = Get-ChildItem -LiteralPath $release -Filter 'Meu-*-win-x64.exe' -File |
  Select-Object -First 1
if (-not $installer) { throw 'Meu Windows installer artifact is missing.' }

Write-Host "Testing $($installer.Name)"
Invoke-SmokeProcess $installer.FullName '/S'

$shell = New-Object -ComObject WScript.Shell
foreach ($location in @('Desktop', 'Programs')) {
  $folder = [Environment]::GetFolderPath($location)
  $shortcutPath = Join-Path $folder 'Meu.lnk'
  if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    throw "Meu shortcut missing in $location ($shortcutPath)"
  }
  $shortcut = $shell.CreateShortcut($shortcutPath)
  if ([IO.Path]::GetFileName($shortcut.TargetPath) -ne 'Meu.exe') {
    throw "Wrong shortcut target at ${shortcutPath}: $($shortcut.TargetPath)"
  }
  if (-not (Test-Path -LiteralPath $shortcut.TargetPath -PathType Leaf)) {
    throw "Meu.exe target missing: $($shortcut.TargetPath)"
  }
  Write-Host "[PASS] $location shortcut -> $($shortcut.TargetPath)"
}

# The shipped Windows executable must carry Meu resources, not the stock Electron/Hermes metadata.
$exe = $shortcut.TargetPath
$info = (Get-Item -LiteralPath $exe).VersionInfo
if ($info.ProductName -ne 'Meu' -or $info.FileDescription -ne 'Meu') {
  throw "Wrong executable identity: $($info.ProductName) / $($info.FileDescription)"
}
$notices = Join-Path (Split-Path $exe) 'resources\open-source-notices\Hermes-LICENSE.txt'
if (-not (Test-Path -LiteralPath $notices)) { throw 'Upstream MIT attribution is missing.' }

# Rehearse actual renderer startup and restart without model credentials or a live backend.
$guiScratch = Join-Path $env:RUNNER_TEMP 'meu-renderer-smoke'
& node (Join-Path $PSScriptRoot 'test-meu-installed.mjs') $exe $guiScratch
if ($LASTEXITCODE -ne 0) { throw 'Packaged renderer launch/restart failed.' }

# A repair/upgrade must preserve user state, and uninstall must leave it available for reinstall.
$profile = Join-Path $env:LOCALAPPDATA 'MeuAgent'
New-Item -ItemType Directory -Path $profile -Force | Out-Null
$proof = Join-Path $profile '.meu-installer-ci-proof'
$proofValue = [guid]::NewGuid().ToString('N')
[IO.File]::WriteAllText($proof, $proofValue)
Invoke-SmokeProcess $installer.FullName '/S'
if ([IO.File]::ReadAllText($proof) -ne $proofValue) { throw 'Repair changed profile state.' }
Write-Host '[PASS] Reinstall/repair preserves the Meu profile'

$uninstaller = Join-Path (Split-Path $exe) 'Uninstall Meu.exe'
if (-not (Test-Path -LiteralPath $uninstaller)) { throw 'Meu uninstaller is missing.' }
Invoke-SmokeProcess $uninstaller '/S'
# NSIS may hand off to a temporary uninstaller before its original process exits.
$deadline = [DateTime]::UtcNow.AddSeconds(30)
while ((Test-Path -LiteralPath $exe) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
if (Test-Path -LiteralPath $exe) { throw 'Uninstall left Meu.exe installed.' }
if ([IO.File]::ReadAllText($proof) -ne $proofValue) { throw 'Uninstall removed profile state.' }
Write-Host '[PASS] Uninstall removes the app and preserves the Meu profile'

Invoke-SmokeProcess $installer.FullName '/S'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Reinstall did not restore Meu.exe.' }
if ([IO.File]::ReadAllText($proof) -ne $proofValue) { throw 'Reinstall lost the preserved profile.' }
Remove-Item -LiteralPath $proof
Write-Host '[PASS] Install/repair/uninstall/reinstall lifecycle completed'
