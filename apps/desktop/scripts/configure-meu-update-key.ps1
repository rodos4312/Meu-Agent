param([Parameter(Mandatory = $true)][string]$GitHubCliPath)

$ErrorActionPreference = 'Stop'
$cli = (Resolve-Path -LiteralPath $GitHubCliPath).Path
& $cli auth status --hostname github.com
if ($LASTEXITCODE -ne 0) { throw 'Sign in through the official GitHub CLI first: gh auth login. No password is read from Git credential storage.' }
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$keyPath = Join-Path $root '.meu-tooling/meu-update-key/private-key.dpapi'
$secure = ConvertTo-SecureString -String (Get-Content -LiteralPath $keyPath -Raw).Trim()
$processInfo = New-Object Diagnostics.ProcessStartInfo
$processInfo.FileName = $cli
$processInfo.Arguments = 'secret set MEU_RELEASE_PRIVATE_KEY --repo rodos4312/Meu-Agent'
$processInfo.UseShellExecute = $false
$processInfo.CreateNoWindow = $true
$processInfo.WindowStyle = 'Hidden'
$processInfo.RedirectStandardInput = $true
$process = [Diagnostics.Process]::Start($processInfo)
try {
    $process.StandardInput.Write(([Net.NetworkCredential]::new('', $secure)).Password)
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(60000)) { throw 'GitHub key configuration timed out.' }
    if ($process.ExitCode -ne 0) { throw 'GitHub refused the update key configuration.' }
} finally {
    $process.Dispose()
    $secure = $null
}
Write-Host 'Configured the free update key in the Meu repository Actions secret. No paid certificate is required.'
