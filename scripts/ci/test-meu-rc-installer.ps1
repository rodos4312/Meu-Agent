$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Disposable GitHub runner only.' }
function Run-Installer([string]$Exe) {
    $child = Start-Process -FilePath $Exe -ArgumentList @('/S','/currentuser') -WindowStyle Hidden -PassThru
    $timer = [Diagnostics.Stopwatch]::StartNew()
    try {
        while (-not $child.WaitForExit(30000)) {
            $child.Refresh()
            $disk = @(Get-PSDrive -PSProvider FileSystem | Where-Object Name -In @('C','D') |
                Select-Object Name,Free,Used)
            $destination = Join-Path $env:LOCALAPPDATA 'Programs/Meu'
            $files = @(Get-ChildItem -LiteralPath $destination -File -Recurse -ErrorAction SilentlyContinue)
            $bytes = ($files | Measure-Object Length -Sum).Sum
            $sample = [ordered]@{ elapsedSeconds=[int]$timer.Elapsed.TotalSeconds; installerPid=$child.Id;
                cpuSeconds=$child.TotalProcessorTime.TotalSeconds; installedFiles=$files.Count;
                installedBytes=$bytes; disks=$disk }
            $json = $sample | ConvertTo-Json -Depth 4 -Compress
            Write-Host $json
            Add-Content -LiteralPath $progress -Value $json -Encoding utf8
            if ($timer.Elapsed.TotalMinutes -ge 30) { throw 'Installer timed out after 30 minutes; see install-progress.jsonl.' }
        }
        if ($child.ExitCode -ne 0) { throw "Installer failed: $($child.ExitCode)" }
        Write-Host "Installer exited successfully after $([int]$timer.Elapsed.TotalSeconds) seconds."
    } finally { $child.Dispose() }
}
$scratch = Join-Path $env:RUNNER_TEMP 'meu-rc-installed-smoke'
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
$progress = Join-Path $scratch 'install-progress.jsonl'
# The scanned build copies are no longer needed. Free space for the real install
# without touching source files or any user installation outside this CI runner.
$workspace = [IO.Path]::GetFullPath($env:GITHUB_WORKSPACE).TrimEnd([IO.Path]::DirectorySeparatorChar)
foreach ($relative in @('apps/desktop/release/win-unpacked','apps/desktop/build/agent-payload','apps/desktop/build/native-deps')) {
    $target = [IO.Path]::GetFullPath((Join-Path $workspace $relative))
    if (-not $target.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Cleanup target is outside the disposable workspace.'
    }
    if (Test-Path -LiteralPath $target) {
        $item = Get-Item -LiteralPath $target
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing a redirected cleanup target.' }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
Get-PSDrive -PSProvider FileSystem | Where-Object Name -In @('C','D') | Select-Object Name,Free,Used | Format-Table
$installer = @(Get-ChildItem apps/desktop/release/Meu-*-win-x64.exe -File)
if ($installer.Count -ne 1) { throw 'Expected one installer.' }
Run-Installer $installer[0].FullName
$exe = Join-Path $env:LOCALAPPDATA 'Programs/Meu/Meu.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Installed Meu.exe missing.' }
$info = (Get-Item -LiteralPath $exe).VersionInfo
if ($info.ProductName -cne 'Meu') { throw 'Incorrect executable branding.' }
node scripts/ci/meu-rc-desktop-smoke.mjs $exe $scratch $env:GITHUB_SHA
if ($LASTEXITCODE -ne 0) { throw 'Installed real-runtime smoke failed.' }
$proof = Join-Path $scratch 'profile/.meu-rc-repair-proof'
$value = [guid]::NewGuid().ToString('N')
[IO.File]::WriteAllText($proof,$value)
Run-Installer $installer[0].FullName
if ([IO.File]::ReadAllText($proof) -cne $value) { throw 'Repair changed the test profile.' }
Write-Host 'PASS: actual installer and repair with preserved isolated profile'
