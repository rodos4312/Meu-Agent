# Build only the unpublished failure fixture, shared by full and diagnostic CI.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:GITHUB_REPOSITORY -cne 'rodos4312/Meu-Agent') {
    throw 'Rollback fixture packaging requires a disposable Meu GitHub runner.'
}
node --input-type=module -e "import fs from 'node:fs'; import {inc} from 'semver'; const p=JSON.parse(fs.readFileSync('package.json')); p.version=inc(p.version,'prerelease','dev'); fs.writeFileSync('package.json',JSON.stringify(p,null,2)+'\n');"
if ($LASTEXITCODE -ne 0) { throw 'Cannot select private fixture version.' }
# The Windows shell relaunch must not need to inherit a test environment flag.
# Only this unpublished fixture replaces the existing startup-failure seam.
$meuMain = Resolve-Path 'electron/main.ts'
$meuMainSource = [System.IO.File]::ReadAllText($meuMain)
$meuFaultSeam = "const BOOT_FAKE_ERROR = process.env.HERMES_DESKTOP_BOOT_FAKE_ERROR || ''"
if (-not $meuMainSource.Contains($meuFaultSeam)) { throw 'Startup-failure fixture seam changed.' }
[System.IO.File]::WriteAllText($meuMain, $meuMainSource.Replace($meuFaultSeam, "const BOOT_FAKE_ERROR = 'Controlled Meu rollback rehearsal'"), [System.Text.UTF8Encoding]::new($false))
$meuConfig = Resolve-Path 'electron-builder.config.cjs'
$meuConfigSource = [System.IO.File]::ReadAllText($meuConfig)
if (-not $meuConfigSource.Contains('  nsis: {')) { throw 'Private NSIS fixture seam changed.' }
[System.IO.File]::WriteAllText($meuConfig, $meuConfigSource.Replace('  nsis: {', "  nsis: {`n    include: 'scripts/meu-interrupted-install.nsh',"), [System.Text.UTF8Encoding]::new($false))
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Private fixture build failed.' }
node scripts/run-electron-builder.mjs --win nsis --x64
if ($LASTEXITCODE -ne 0) { throw 'Private fixture packaging failed.' }
$installer = Get-ChildItem -LiteralPath release -Filter 'Meu-*-win-x64.exe' -File
if (@($installer).Count -ne 1) { throw 'Expected exactly one private fixture installer.' }
./scripts/scan-meu-package.ps1 -PackagePath $installer.FullName -ReportDirectory release/security -UnpackedPath release/win-unpacked
