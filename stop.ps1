# Stop Inferago IOI started with start.ps1.
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "backend\data\ioi.pid"
if (Test-Path $PidFile) {
  $procId = Get-Content $PidFile
  $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
  if ($p) { Stop-Process -Id $procId; Write-Host "IOI stopped." } else { Write-Host "IOI was not running." }
  Remove-Item $PidFile
} else { Write-Host "IOI was not running." }
