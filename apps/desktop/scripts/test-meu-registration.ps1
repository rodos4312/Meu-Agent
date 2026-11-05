# Read-only contract shared by the real Windows install, upgrade and rollback rehearsals.
param(
  [Parameter(Mandatory = $true)][string]$Executable,
  [Parameter(Mandatory = $true)][string]$Version
)
$ErrorActionPreference = 'Stop'
$exe = Get-Item -LiteralPath $Executable
if ($exe.Name -cne 'Meu.exe' -or $exe.VersionInfo.ProductName -cne 'Meu') {
  throw 'Expected an installed Meu executable.'
}
if ($exe.VersionInfo.FileVersion -cne $Version) {
  throw "Installed executable version differs: $($exe.VersionInfo.FileVersion), expected $Version."
}
$uninstaller = Join-Path $exe.DirectoryName 'Uninstall Meu.exe'
$registrations = @(
  foreach ($hive in @([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryHive]::LocalMachine)) {
    $root = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, [Microsoft.Win32.RegistryView]::Registry64)
    try {
      $uninstall = $root.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall')
      if (-not $uninstall) { continue }
      try {
        foreach ($name in $uninstall.GetSubKeyNames()) {
          $entry = $uninstall.OpenSubKey($name)
          try {
            if ($entry.GetValue('DisplayName') -cne 'Meu') { continue }
            # Match the installed path, not another user's or a second Meu installation.
            $command = [string]$entry.GetValue('UninstallString')
            if ($command -notmatch '^"([^"]+)"(?:\s|$)' -or $Matches[1] -ine $uninstaller) { continue }
            [pscustomobject]@{ Hive = [string]$hive; Key = $name; Version = $entry.GetValue('DisplayVersion') }
          } finally { $entry.Dispose() }
        }
      } finally { $uninstall.Dispose() }
    } finally { $root.Dispose() }
  }
)
if ($registrations.Count -ne 1) { throw "Expected one Meu uninstall registration for this installation; found $($registrations.Count)." }
if ($registrations[0].Version -cne $Version) {
  throw "Windows lists Meu $($registrations[0].Version), but the installed executable is $Version."
}
Write-Host "[PASS] Windows uninstall registration and executable both report Meu $Version"
