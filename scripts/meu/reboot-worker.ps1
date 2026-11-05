param([ValidateSet('prepare','reboot')][string]$Stage)
$ErrorActionPreference='Stop'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:GITHUB_REPOSITORY -cne 'rodos4312/Meu-Agent' -or
    $env:GITHUB_REF -cne 'refs/heads/dev/meu-foundation' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $env:RUNNER_OS -cne 'Windows' -or $env:GITHUB_RUN_ID -notmatch '^\d+$' -or $env:GITHUB_RUN_ATTEMPT -notmatch '^\d+$') {
  throw 'Reboot is restricted to a disposable GitHub-hosted Meu Windows runner.'
}
$root=Join-Path $env:ProgramData "MeuRebootProbe-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
$public=Join-Path $env:RUNNER_TEMP 'meu-reboot-public'
$private=Join-Path $root 'private.bin'
$context=Join-Path $root 'context.json'
if ($Stage -eq 'prepare') {
  if (Test-Path -LiteralPath $root) { throw 'Probe requires a fresh directory.' }
  New-Item -ItemType Directory -Path $root,$public | Out-Null
  & icacls.exe $root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Could not restrict the private probe directory.' }
  $rsa=[Security.Cryptography.RSA]::Create(3072)
  try {
    [IO.File]::WriteAllText((Join-Path $public 'public.pem'),$rsa.ExportSubjectPublicKeyInfoPem())
    $encrypted=[Security.Cryptography.ProtectedData]::Protect($rsa.ExportPkcs8PrivateKey(),$null,[Security.Cryptography.DataProtectionScope]::LocalMachine)
    [IO.File]::WriteAllBytes($private,$encrypted)
  } finally { $rsa.Dispose() }
  $baseline=@{schema=1;run=$env:GITHUB_RUN_ID;attempt=$env:GITHUB_RUN_ATTEMPT;nonce=[guid]::NewGuid().ToString('N');
    before_boot_utc=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o');sha=$env:GITHUB_SHA}
  $baseline | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $public 'baseline.json') -Encoding utf8
  $baseline | ConvertTo-Json | Set-Content -LiteralPath $context -Encoding utf8
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'reboot-receipt.ps1') -Destination (Join-Path $root 'receipt.ps1')
  exit 0
}
$deadline=[DateTime]::UtcNow.AddMinutes(8)
do {
  $inventory=(& gh api "repos/rodos4312/Meu-Agent/actions/runs/$env:GITHUB_RUN_ID/artifacts?per_page=100" | ConvertFrom-Json)
  $found=@($inventory.artifacts | Where-Object { $_.name -eq "meu-reboot-envelope-$env:GITHUB_RUN_ATTEMPT" })
  if ($found.Count -gt 0) { break }
  Start-Sleep -Seconds 5
} while ([DateTime]::UtcNow -lt $deadline)
if ($found.Count -eq 0) { throw 'The encrypted controller token did not arrive.' }
& gh run download $env:GITHUB_RUN_ID --repo rodos4312/Meu-Agent --name "meu-reboot-envelope-$env:GITHUB_RUN_ATTEMPT" --dir $root
if ($LASTEXITCODE -ne 0) { throw 'Could not download the encrypted controller envelope.' }
$action=New-ScheduledTaskAction -Execute (Get-Command pwsh).Source -Argument ('-NoProfile -NonInteractive -File "'+(Join-Path $root 'receipt.ps1')+'" -Root "'+$root+'"')
$trigger=New-ScheduledTaskTrigger -AtStartup
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "MeuRebootProbe-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT" -Action $action -Trigger $trigger -Principal $principal | Out-Null
Write-Host 'Prepared the independent post-boot receipt; rebooting only this disposable CI VM.'
& shutdown.exe /r /t 5 /f
if ($LASTEXITCODE -ne 0) { throw 'The disposable VM refused the reboot.' }
Start-Sleep -Seconds 600
throw 'The reboot did not terminate the original workflow process.'
