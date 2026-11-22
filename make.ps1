<#
.SYNOPSIS
    NightShift PowerShell Task Runner (Windows equivalent to make)
.DESCRIPTION
    Supports commands: up, test, demo, reset, lint, check-owners
.EXAMPLE
    .\make.ps1 up
    .\make.ps1 test
    .\make.ps1 demo -Fault 1
    .\make.ps1 reset
#>

param(
    [Parameter(Position=0, Mandatory=$false)]
    [ValidateSet("help", "up", "test", "demo", "reset", "lint", "check-owners", "traffic")]
    [string]$Target = "help",

    [Parameter(Mandatory=$false)]
    [string]$Fault = "",

    [Parameter(Mandatory=$false)]
    [double]$Rate = 10.0,

    [Parameter(Mandatory=$false)]
    [double]$Duration = 0.0
)

$ErrorActionPreference = "Stop"

switch ($Target) {
    "traffic" {
        $cmd = "python run.py traffic --rate $Rate"
        if ($Duration -gt 0) {
            $cmd += " --duration $Duration"
        }
        Invoke-Expression $cmd
    }
    "up" {
        python run.py up
    }
    "test" {
        python run.py test
    }
    "lint" {
        python run.py lint
    }
    "demo" {
        if (-not $Fault) {
            Write-Error "Please specify -Fault <id>, e.g.: .\make.ps1 demo -Fault 1"
        }
        python run.py demo --fault $Fault
    }
    "reset" {
        python run.py reset
    }
    "check-owners" {
        python run.py check-owners
    }
    Default {
        Write-Host "NightShift - Autonomous AI On-Call Engineer (PowerShell Runner)" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Commands:"
        Write-Host "  .\make.ps1 up                 Start target app, telemetry, and platform API"
        Write-Host "  .\make.ps1 test               Run linters and complete test suite"
        Write-Host "  .\make.ps1 demo -Fault <id>   Run autonomous incident loop for given fault"
        Write-Host "  .\make.ps1 reset              Reset containers, clean caches and worktrees"
        Write-Host "  .\make.ps1 lint               Run code quality & syntax checks"
        Write-Host "  .\make.ps1 check-owners       Validate directory ownership policy"
        Write-Host ""
    }
}
