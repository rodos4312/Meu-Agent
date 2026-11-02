param(
  [switch]$Watch,
  [string]$Scratch
)

$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:GITHUB_REPOSITORY -cne 'rodos4312/Meu-Agent') {
  throw 'Native upgrade rehearsal is restricted to a disposable Meu GitHub runner.'
}
$expectedScratch = [IO.Path]::GetFullPath((Join-Path $env:RUNNER_TEMP 'meu-native-upgrade'))
if (-not $Scratch) { $Scratch = $expectedScratch }
if ([IO.Path]::GetFullPath($Scratch) -cne $expectedScratch) { throw 'Unexpected rehearsal directory.' }

if ($Watch) {
  # Legacy dev.8 still opens NSIS's wizard. Only advance that Meu setup window.
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  $deadline = [DateTime]::UtcNow.AddMinutes(8)
  $clicks = 0
  while (-not (Test-Path -LiteralPath (Join-Path $Scratch '.native-upgrade-done')) -and [DateTime]::UtcNow -lt $deadline) {
    $windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
      [System.Windows.Automation.TreeScope]::Children,
      [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ClassNameProperty, '#32770'))
    foreach ($window in $windows) {
      if ($window.Current.Name -notmatch '^Meu(?:\s|$)') { continue }
      $buttons = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,
          [System.Windows.Automation.ControlType]::Button))
      foreach ($button in $buttons) {
        if ($button.Current.IsEnabled -and $button.Current.Name -match '^&?(Next\s*>?|Install|Finish)$') {
          try {
            $invoke = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
            $invoke.Invoke()
            $clicks++
          } catch [System.Windows.Automation.ElementNotAvailableException] { }
          break
        }
      }
    }
    Start-Sleep -Milliseconds 300
  }
  @{ legacyWizardClicks = $clicks } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Scratch 'legacy-wizard.json') -Encoding utf8
  exit 0
}

New-Item -ItemType Directory -Path $Scratch -Force | Out-Null
$baseline = Join-Path $env:RUNNER_TEMP 'meu-baseline-candidate'
$candidate = Join-Path $env:RUNNER_TEMP 'meu-target-candidate'
$driver = Join-Path $PSScriptRoot 'test-meu-native-upgrade.mjs'
& node $driver validate $baseline $candidate $Scratch
if ($LASTEXITCODE -ne 0) { throw 'Candidate signature/hash validation failed before installation.' }
$old = Get-Content -LiteralPath (Join-Path $baseline 'meu-release.json') -Raw | ConvertFrom-Json
if ($old.version -cne '0.1.0-dev.8' -or $old.commit -cne '2895c40af3ffa4cff6f61b518573dda3c260ae25') {
  throw 'The baseline does not match the pinned, tested Meu dev.8 release.'
}
$executable = Join-Path $env:LOCALAPPDATA 'Programs\Meu\Meu.exe'
if (Test-Path -LiteralPath $executable) { throw 'Rehearsal requires a fresh runner without an existing Meu installation.' }
$installer = Start-Process -FilePath (Join-Path $baseline $old.file) -ArgumentList '/S' -WindowStyle Hidden -PassThru
try {
  if (-not $installer.WaitForExit(180000)) { throw 'Baseline installation exceeded 180 seconds.' }
  if ($installer.ExitCode -ne 0) { throw "Baseline installer exited $($installer.ExitCode)." }
} finally { $installer.Dispose() }
if (-not (Test-Path -LiteralPath $executable)) { throw 'Baseline Meu executable is missing.' }

$watcher = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru -ArgumentList @(
  '-STA', '-NoProfile', '-NonInteractive', '-File', ('"' + $PSCommandPath + '"'), '-Watch', '-Scratch', ('"' + $Scratch + '"'))
try {
  & node $driver run $baseline $candidate $Scratch $executable
  if ($LASTEXITCODE -ne 0) { throw 'Real native update rehearsal failed.' }
} finally {
  New-Item -ItemType File -Path (Join-Path $Scratch '.native-upgrade-done') -Force | Out-Null
  if (-not $watcher.WaitForExit(10000)) { Stop-Process -Id $watcher.Id -Force -ErrorAction SilentlyContinue }
  $watcher.Dispose()
}
