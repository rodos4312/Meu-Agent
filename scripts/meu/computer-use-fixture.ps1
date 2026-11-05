param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$root=[IO.Path]::GetFullPath($Directory)
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'Create a fresh probe directory first.' }
$form=[Windows.Forms.Form]::new()
$form.Text='Meu isolated input rehearsal'
$form.Width=540
$form.Height=250
$form.StartPosition='CenterScreen'
$inputBox=[Windows.Forms.TextBox]::new()
$inputBox.AccessibleName='Meu probe input'
$inputBox.SetBounds(25,25,470,35)
$button=[Windows.Forms.Button]::new()
$button.Text='Record test value'
$button.AccessibleName='Record test value'
$button.SetBounds(25,80,190,40)
$reset=[Windows.Forms.Button]::new()
$reset.Text='Clear test value'
$reset.AccessibleName='Clear test value'
$reset.SetBounds(230,80,190,40)
$reset.Add_Click({$inputBox.Clear(); $inputBox.Focus() | Out-Null})
$label=[Windows.Forms.Label]::new()
$label.SetBounds(25,140,470,30)
$label.Text='Synthetic data only; this window closes automatically.'
$button.Add_Click({
  $label.Text=$inputBox.Text
  @{value=$inputBox.Text;pid=$PID;recorded_utc=[DateTime]::UtcNow.ToString('o')} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'observed.json') -Encoding utf8
})
$form.Controls.AddRange(@($inputBox,$button,$reset,$label))
$form.Add_Shown({
  @{pid=$PID;window_id=$form.Handle.ToInt64()} | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $root 'ready.json') -Encoding utf8
})
$timer=[Windows.Forms.Timer]::new()
$timer.Interval=300000
$timer.Add_Tick({$form.Close()})
$timer.Start()
try { [Windows.Forms.Application]::Run($form) }
finally { $timer.Stop();$timer.Dispose();$form.Dispose() }
