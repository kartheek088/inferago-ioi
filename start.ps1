# Start Inferago IOI on Windows (PowerShell). Run:  powershell -ExecutionPolicy Bypass -File .\start.ps1
# Checks requirements, installs what's missing, builds the web app if needed, starts IOI in the background.
# Stop with .\stop.ps1. Logs: backend\data\ioi.log
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = Join-Path $Root "backend\data"
$PidFile = Join-Path $Data "ioi.pid"
$Log = Join-Path $Data "ioi.log"
New-Item -ItemType Directory -Force -Path $Data | Out-Null
function Fail($m) { Write-Host "Problem: $m" -ForegroundColor Red; exit 1 }

$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Root ".env.example") $EnvFile; Write-Host "Created .env from .env.example" }
$Port = (Select-String -Path $EnvFile -Pattern '^IOI_PORT=(.*)$' | Select-Object -Last 1).Matches.Groups[1].Value
if (-not $Port) { $Port = "8000" }
$Url = "http://127.0.0.1:$Port"

try { Invoke-WebRequest "$Url/api/v3/status" -UseBasicParsing -TimeoutSec 2 | Out-Null; Write-Host "IOI is already running: $Url"; exit 0 } catch {
  if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) { Write-Host "IOI is already running: $Url"; exit 0 }
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Fail "Python 3.11+ is not installed. Get it from https://www.python.org/downloads/ (tick 'Add to PATH')." }
& python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; if ($LASTEXITCODE -ne 0) { Fail "Python 3.11 or newer is needed." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "Node.js 18+ is not installed. Get it from https://nodejs.org/" }

Set-Location (Join-Path $Root "backend")
$VenvPy = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$Marker = ".venv\.ioi-installed"
if (Get-Command uv -ErrorAction SilentlyContinue) {
  if (-not (Test-Path $Marker) -or (Get-Item uv.lock).LastWriteTime -gt (Get-Item $Marker).LastWriteTime) { Write-Host "Installing backend packages (uv)..."; uv sync --quiet; New-Item -Force $Marker | Out-Null }
} else {
  if (-not (Test-Path $VenvPy)) { Write-Host "Creating Python environment..."; python -m venv .venv }
  if (-not (Test-Path $Marker) -or (Get-Item pyproject.toml).LastWriteTime -gt (Get-Item $Marker).LastWriteTime) {
    Write-Host "Installing backend packages (pip)..."
    & $VenvPy -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" | Set-Content .venv\requirements.txt
    & $VenvPy -m pip install --quiet -r .venv\requirements.txt; if ($LASTEXITCODE -ne 0) { Fail "Installing Python packages failed." }
    New-Item -Force $Marker | Out-Null
  }
}

Set-Location (Join-Path $Root "frontend")
if (-not (Test-Path node_modules)) { Write-Host "Installing web app packages..."; npm ci --no-audit --no-fund --loglevel=error }
if (-not (Test-Path dist\index.html)) { Write-Host "Building the web app..."; npm run build | Out-Null }

Set-Location (Join-Path $Root "backend")
Write-Host "Starting IOI..."
$p = Start-Process -FilePath $VenvPy -ArgumentList "-m", "app.main" -RedirectStandardOutput $Log -RedirectStandardError "$Log.err" -WindowStyle Hidden -PassThru
$p.Id | Set-Content $PidFile
for ($i = 0; $i -lt 60; $i++) {
  try { Invoke-WebRequest "$Url/api/v3/status" -UseBasicParsing -TimeoutSec 2 | Out-Null; $ok = $true } catch {
    $ok = $_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401 }
  if ($ok) { Write-Host "IOI is running. Open: $Url   (stop with .\stop.ps1)" -ForegroundColor Green; Start-Process $Url; exit 0 }
  if ($p.HasExited) { Get-Content "$Log.err" -Tail 20; Fail "IOI stopped while starting (see above)." }
  Start-Sleep -Seconds 1
}
Fail "IOI did not respond within 60 seconds. See $Log"
