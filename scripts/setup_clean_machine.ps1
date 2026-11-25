<#
.SYNOPSIS
  NightShift One-Command Clean Machine Setup & Demo Verification (Day 10 Task A4).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/setup_clean_machine.ps1
#>
param(
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$Start = Get-Date

Write-Host "==> [NightShift Setup] Checking prerequisites (python, git)..."
$null = Get-Command python -ErrorAction Stop
$null = Get-Command git -ErrorAction Stop

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Write-Host "==> Creating .env from .env.example..."
    Copy-Item ".env.example" ".env"
}

if (-not $VerifyOnly) {
    Write-Host "==> Installing Python dependencies..."
    python -m pip install -r requirements.txt -r requirements-dev.txt
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try {
            docker info *> $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "==> Starting docker compose stack..."
                docker compose -f infra/docker-compose.yml up -d
            }
        } catch {
            Write-Host "==> Docker daemon not active; continuing in local mode."
        }
    }
}

Write-Host "==> Validating CODEOWNERS and running end-to-end demo..."
python run.py check-owners
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python run.py demo --fault fault_001_bad_deploy
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Elapsed = ((Get-Date) - $Start).TotalSeconds
Write-Host ("==> [NightShift Setup] Completed in {0:N1}s (limit: 900s / 15 minutes)." -f $Elapsed)
if ($Elapsed -ge 900) {
    Write-Error "Setup + demo exceeded 15-minute SLA!"
    exit 1
}
