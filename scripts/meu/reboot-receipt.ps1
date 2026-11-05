param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference='Stop'
$directory=[IO.Path]::GetFullPath($Root)
if ($directory -notmatch '\\ProgramData\\MeuRebootProbe-\d+-\d+$') { throw 'Not an owned CI reboot directory.' }
$baseline=Get-Content -LiteralPath (Join-Path $directory 'context.json') -Raw | ConvertFrom-Json
$after=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
if ($after -le [DateTime]::Parse($baseline.before_boot_utc).ToUniversalTime()) { throw 'A new Windows boot was not observed.' }
$rsa=[Security.Cryptography.RSA]::Create()
try {
  $key=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Join-Path $directory 'private.bin')),$null,[Security.Cryptography.DataProtectionScope]::LocalMachine)
  $read=0
  $rsa.ImportPkcs8PrivateKey($key,[ref]$read)
  $token=[Text.Encoding]::UTF8.GetString($rsa.Decrypt([IO.File]::ReadAllBytes((Join-Path $directory 'envelope.bin')),[Security.Cryptography.RSAEncryptionPadding]::OaepSHA256))
} finally { $rsa.Dispose() }
$proof=@{schema=1;run=$baseline.run;attempt=$baseline.attempt;nonce=$baseline.nonce;
  before_boot_utc=$baseline.before_boot_utc;after_boot_utc=$after.ToString('o');observed_utc=[DateTime]::UtcNow.ToString('o');
  realWindowsReboot=$true;meuRecoveryTested=$false}
$proof | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $directory 'receipt.json') -Encoding utf8
$body=@{name='Meu reboot receipt';head_sha=$baseline.sha;external_id="$($baseline.run)-$($baseline.attempt)";status='completed';conclusion='success';
  output=@{title='Observed a real later Windows boot';summary=($proof | ConvertTo-Json -Compress)}} | ConvertTo-Json -Depth 5
try {
  Invoke-RestMethod -Uri 'https://api.github.com/repos/rodos4312/Meu-Agent/check-runs' -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json' -Headers @{Authorization="Bearer $token";'X-GitHub-Api-Version'='2022-11-28'} | Out-Null
} finally {
  Remove-Item -LiteralPath (Join-Path $directory 'private.bin'),(Join-Path $directory 'envelope.bin')
  Unregister-ScheduledTask -TaskName "MeuRebootProbe-$($baseline.run)-$($baseline.attempt)" -Confirm:$false
}
