param(
  [Parameter(Mandatory=$true)][string]$PackagePath,
  [Parameter(Mandatory=$true)][string]$ReportDirectory,
  [string]$ExpectedPublisher = '',
  [string]$UnpackedPath = ''
)
$ErrorActionPreference = 'Stop'
$package = Get-Item -LiteralPath $PackagePath
if ($package.PSIsContainer -or $package.Name -notlike 'Meu-*-win-x64.exe') { throw 'Expected a Meu Windows installer.' }
$report = [IO.Path]::GetFullPath($ReportDirectory)
New-Item -ItemType Directory -Path $report -Force | Out-Null
$result = [ordered]@{
  schema=1; file=$package.Name; bytes=$package.Length
  sha256=(Get-FileHash -LiteralPath $package.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  sha512=[Convert]::ToBase64String([Security.Cryptography.SHA512]::Create().ComputeHash([IO.File]::ReadAllBytes($package.FullName)))
  status='incomplete'; engine=$null; signature=$null; scans=@(); completedAt=$null
}
try {
  $status = Get-MpComputerStatus
  if (-not $status.AMServiceEnabled -or -not $status.AntivirusEnabled) { throw 'Defender is unavailable; this package cannot be published.' }
  $result.engine = @{ version=$status.AMProductVersion; definitions=$status.AntivirusSignatureVersion; updatedAt=$status.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o') }
  $scanner = Get-ChildItem -LiteralPath (Join-Path $env:ProgramData 'Microsoft\Windows Defender\Platform') -Directory |
    Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'MpCmdRun.exe' } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
  if (-not $scanner) { throw 'Defender command-line scanner is missing.' }
  $targets = @($package.FullName)
  if ($UnpackedPath) { $targets += (Get-Item -LiteralPath $UnpackedPath).FullName }
  foreach ($target in $targets) {
    $index = $result.scans.Count
    # Scan archives and ignore exclusions, without deleting or quarantining test outputs.
    & $scanner -Scan -ScanType 3 -File $target -DisableRemediation 2>&1 |
      Tee-Object -FilePath (Join-Path $report "defender-$index.log") | Write-Host
    $code = $LASTEXITCODE
    $result.scans += @{ target=[IO.Path]::GetFileName($target); exitCode=$code }
    if ($code -ne 0) { throw "Defender scan failed or reported a detection (exit $code)." }
  }
  $sig = Get-AuthenticodeSignature -LiteralPath $package.FullName
  $subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { $null }
  $result.signature = @{ status=$sig.Status.ToString(); type=$sig.SignatureType.ToString(); subject=$subject }
  if ($ExpectedPublisher -and ($sig.Status -ne 'Valid' -or $sig.SignatureType -ne 'Authenticode' -or $subject -cne $ExpectedPublisher)) {
    throw 'Installer has no valid embedded signature from the expected Meu publisher.'
  }
  $result.status = 'clean'
} catch {
  $result.status = 'failed'
  $result.error = $_.Exception.Message
  throw
} finally {
  $result.completedAt = [DateTime]::UtcNow.ToString('o')
  $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $report 'meu-package-security.json') -Encoding utf8
  "$($result.sha256)  $($package.Name)" | Set-Content -LiteralPath (Join-Path $report 'SHA256SUMS.txt') -Encoding ascii
}
