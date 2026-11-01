# Smoke-check the unsigned Meu development installer on an ephemeral Windows CI runner.
# No model/API credentials are needed, and the installed app is not launched.
$ErrorActionPreference = 'Stop'
$release = Join-Path $PSScriptRoot '..\release'
$installer = Get-ChildItem -LiteralPath $release -Filter 'Meu-*-win-x64.exe' -File |
  Select-Object -First 1
if (-not $installer) { throw 'Meu Windows installer artifact is missing.' }

Write-Host "Testing $($installer.Name)"
$process = Start-Process -FilePath $installer.FullName -ArgumentList '/S' -PassThru
try {
  if (-not $process.WaitForExit(180000)) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw 'Meu silent installer exceeded 180 seconds.'
  }
  if ($process.ExitCode -ne 0) {
    throw "Meu installer exit code: $($process.ExitCode)"
  }
} finally {
  $process.Dispose()
}

$shell = New-Object -ComObject WScript.Shell
foreach ($location in @('Desktop', 'Programs')) {
  $folder = [Environment]::GetFolderPath($location)
  $shortcutPath = Join-Path $folder 'Meu.lnk'
  if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    throw "Meu shortcut missing in $location ($shortcutPath)"
  }
  $shortcut = $shell.CreateShortcut($shortcutPath)
  if ([IO.Path]::GetFileName($shortcut.TargetPath) -ne 'Meu.exe') {
    throw "Wrong shortcut target at $shortcutPath: $($shortcut.TargetPath)"
  }
  if (-not (Test-Path -LiteralPath $shortcut.TargetPath -PathType Leaf)) {
    throw "Meu.exe target missing: $($shortcut.TargetPath)"
  }
  Write-Host "[PASS] $location shortcut -> $($shortcut.TargetPath)"
}
