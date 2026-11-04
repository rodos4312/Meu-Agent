# Probe a disposable GitHub Windows VM before admitting a real reboot rehearsal.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:GITHUB_REPOSITORY -cne 'rodos4312/Meu-Agent' -or
    $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or $env:GITHUB_REF -cne 'refs/heads/dev/meu-foundation') {
    throw 'Cold boot testing is restricted to the disposable Meu GitHub VM.'
}
if ($env:GITHUB_SHA -cnotmatch '^[a-f0-9]{40}$') { throw 'Missing test build identity.' }
$meuHeaders = @{ Authorization = "Bearer $env:GH_TOKEN"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
$meuCheck = Invoke-RestMethod -Method Post -Uri 'https://api.github.com/repos/rodos4312/Meu-Agent/check-runs' -Headers $meuHeaders -ContentType 'application/json' -Body (@{
    name = 'Meu isolated cold boot proof'; head_sha = $env:GITHUB_SHA; status = 'in_progress'
    external_id = "meu-cold-boot-$env:GITHUB_RUN_ID"
    output = @{title = 'Waiting for a real Windows reboot'; summary = 'A disposable runner must report a different OS boot after restart.'}
} | ConvertTo-Json -Depth 5)
try {
$meuProof = Join-Path $env:ProgramData "MeuColdBootProof/$env:GITHUB_RUN_ID"
New-Item -ItemType Directory -Path $meuProof | Out-Null
$meuTask = "MeuColdBootProof-$env:GITHUB_RUN_ID"
$meuConfig = Join-Path $meuProof 'private-job-context.json'
@{ token = $env:GH_TOKEN; check = $meuCheck.id; task = $meuTask
   boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath $meuConfig -Encoding utf8
$meuSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& "$env:SystemRoot\System32\icacls.exe" $meuConfig /inheritance:r /grant:r "*${meuSid}:(F)" '*S-1-5-18:(F)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot protect the temporary job credential.' }
$meuStartup = Join-Path $meuProof 'report-after-boot.ps1'
@'
$ErrorActionPreference = 'Stop'
$config = Join-Path $PSScriptRoot 'private-job-context.json'
$saved = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
if ($boot -le [DateTime]::Parse($saved.boot).ToUniversalTime()) {
    'Startup task dry run succeeded.' | Set-Content (Join-Path $PSScriptRoot 'dry-run.log')
    exit 0
}
$headers = @{Authorization = "Bearer $($saved.token)"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28'}
$body = @{status = 'completed'; conclusion = 'success'; completed_at = [DateTime]::UtcNow.ToString('o')
    output = @{title = 'Observed a real Windows cold restart'; summary = "Disposable VM boot changed from $($saved.boot) to $($boot.ToString('o')). The task ran under the original test user's S4U identity."}
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Patch -Uri "https://api.github.com/repos/rodos4312/Meu-Agent/check-runs/$($saved.check)" -Headers $headers -ContentType 'application/json' -Body $body | Out-Null
Remove-Item -LiteralPath $config
Unregister-ScheduledTask -TaskName $saved.task -Confirm:$false
'Cold restart proof reported.' | Set-Content (Join-Path $PSScriptRoot 'result.log')
'@ | Set-Content -LiteralPath $meuStartup -Encoding utf8
$meuAction = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$meuStartup`""
$meuTrigger = New-ScheduledTaskTrigger -AtStartup
$meuTrigger.Delay = 'PT15S'
$meuPrincipal = New-ScheduledTaskPrincipal -UserId $meuSid -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $meuTask -Action $meuAction -Trigger $meuTrigger -Principal $meuPrincipal | Out-Null
Start-ScheduledTask -TaskName $meuTask
$meuDeadline = [DateTime]::UtcNow.AddSeconds(30)
while (-not (Test-Path -LiteralPath (Join-Path $meuProof 'dry-run.log'))) {
    if ([DateTime]::UtcNow -ge $meuDeadline) { throw 'Startup task dry run failed; refusing reboot.' }
    [Threading.ManualResetEvent]::new($false).WaitOne(250) | Out-Null
}
Write-Host "Isolated cold boot proof check: $($meuCheck.id)"
# The hosted agent must not finish/revoke the job before the startup proof runs.
# Suspend only the current job's actual runner ancestors, never unrelated processes.
@'
import os,psutil
assert os.environ['GITHUB_REPOSITORY']=='rodos4312/Meu-Agent'
assert os.environ['RUNNER_ENVIRONMENT']=='github-hosted'
parents=[p for p in psutil.Process().parents() if p.name().lower() in ('runner.worker.exe','runner.listener.exe')]
assert any(p.name().lower()=='runner.worker.exe' for p in parents), 'No owned runner ancestor'
for parent in parents: parent.suspend()
'@ | python -
if ($LASTEXITCODE -ne 0) { throw 'Could not retain the disposable test job; refusing reboot.' }
& "$env:SystemRoot\System32\shutdown.exe" /r /f /t 0
if ($LASTEXITCODE -ne 0) { throw 'Disposable VM reboot was refused.' }
[Threading.ManualResetEvent]::new($false).WaitOne(600000) | Out-Null
} catch {
    $meuFailure = @{status = 'completed'; conclusion = 'failure'; output = @{
        title = 'Cold boot proof did not start'; summary = 'The disposable VM preflight failed before a verified reboot receipt.'
    }} | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Method Patch -Uri "https://api.github.com/repos/rodos4312/Meu-Agent/check-runs/$($meuCheck.id)" -Headers $meuHeaders -ContentType 'application/json' -Body $meuFailure | Out-Null
    if ($meuTask -and (Get-ScheduledTask -TaskName $meuTask -ErrorAction SilentlyContinue)) {
        Unregister-ScheduledTask -TaskName $meuTask -Confirm:$false
    }
    if ($meuConfig -and (Test-Path -LiteralPath $meuConfig)) { Remove-Item -LiteralPath $meuConfig }
    throw
}
