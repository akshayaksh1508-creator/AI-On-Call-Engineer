<#
.SYNOPSIS
    NightShift Target App Deployment Script (Windows PowerShell)
.DESCRIPTION
    Sets the running version label and emits a structured change event.
.EXAMPLE
    .\target-app\deploy.ps1 v1.0.1
    .\target-app\deploy.ps1 2.0.0
#>

param(
    [Parameter(Position=0, Mandatory=$true)]
    [string]$Ref
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
$versionFile = Join-Path $scriptDir "version.txt"
$changesDir = Join-Path $rootDir "data"
$changesFile = Join-Path $changesDir "changes.json"

# Read previous version
$prevVersion = "1.0.0"
if (Test-Path $versionFile) {
    $prevVersion = (Get-Content $versionFile).Trim()
}

# Check git ref if git repo exists
$gitDir = Join-Path $scriptDir ".git"
if (Test-Path $gitDir) {
    Write-Host "==> Checking ref '$Ref' in target-app git repository..." -ForegroundColor Cyan
    try {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $gitOut = & git -C $scriptDir rev-parse --verify $Ref 2>&1
        $gitExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEap

        if ($gitExit -eq 0 -and $gitOut) {
            $short = (& git -C $scriptDir rev-parse --short $Ref 2>$null).Trim()
            Write-Host "==> Resolved ref '$Ref' to commit $short" -ForegroundColor Green
        } else {
            Write-Host "==> Note: '$Ref' recorded as version label." -ForegroundColor Gray
        }
    } catch {
        Write-Host "==> Note: '$Ref' recorded as version label." -ForegroundColor Gray
    }
}

# Write new version to version.txt
Set-Content -Path $versionFile -Value $Ref -NoNewline

# Record change event in data/changes.json
if (-not (Test-Path $changesDir)) {
    New-Item -ItemType Directory -Path $changesDir -Force | Out-Null
}

$nowIso = [System.DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$eventId = "chg_" + [System.DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + "_" + (Get-Random -Minimum 1000 -Maximum 9999)

$events = @()
if (Test-Path $changesFile) {
    try {
        $raw = Get-Content $changesFile -Raw
        if ($raw) {
            $events = $raw | ConvertFrom-Json
            if ($events -isnot [System.Collections.IEnumerable]) {
                $events = @($events)
            }
        }
    } catch {
        $events = @()
    }
}

$newEvent = [PSCustomObject]@{
    id           = $eventId
    type         = "deploy"
    service      = "all"
    from_version = $prevVersion
    to_version   = $Ref
    ref          = $Ref
    author       = $env:USERNAME
    timestamp    = $nowIso
}

$events += $newEvent
$events | ConvertTo-Json -Depth 5 | Set-Content -Path $changesFile

Write-Host "==> [DEPLOY] Successfully deployed ref: '$Ref'" -ForegroundColor Green
Write-Host "==> Version changed: '$prevVersion' -> '$Ref'" -ForegroundColor White
Write-Host "==> Health endpoints (/health) now reporting version: $Ref" -ForegroundColor Green
