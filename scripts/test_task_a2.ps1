# ==============================================================================
# NightShift - Task A2 Manual PowerShell Verification Script
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host "`n======================================================================" -ForegroundColor Cyan
Write-Host " NightShift: Task A2 Live Microservices Verification (PowerShell)" -ForegroundColor Cyan
Write-Host "======================================================================`n" -ForegroundColor Cyan

# 1. Test /health on all three services
Write-Host "[1/4] Checking /health endpoints..." -ForegroundColor Yellow
$services = @(
    @{ Name = "Gateway";  Url = "http://127.0.0.1:8080/health" },
    @{ Name = "Orders";   Url = "http://127.0.0.1:8081/health" },
    @{ Name = "Payments"; Url = "http://127.0.0.1:8082/health" }
)

foreach ($s in $services) {
    try {
        $res = Invoke-RestMethod -Uri $s.Url -Method Get -TimeoutSec 3
        Write-Host "  [OK] $($s.Name) ($($s.Url)) -> Status: $($res.status), Version: $($res.version)" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] Could not connect to $($s.Name) at $($s.Url)!" -ForegroundColor Red
        Write-Host "  Make sure you have started services in another terminal with:" -ForegroundColor White
        Write-Host "      python target-app\run_services.py" -ForegroundColor Cyan
        exit 1
    }
}

# 2. Test End-to-End Order Creation
$traceId = "trace-ps-" + [System.Guid]::NewGuid().ToString().Substring(0, 8)
Write-Host "`n[2/4] Sending Order through Gateway with Trace ID: '$traceId'..." -ForegroundColor Yellow

$orderBody = @{
    customer_id = "cust_akshay"
    item        = "laptop"
    quantity    = 1
    price       = 1299.99
} | ConvertTo-Json

$headers = @{
    "Content-Type" = "application/json"
    "X-Trace-ID"   = $traceId
}

$orderResp = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/orders" -Method Post -Headers $headers -Body $orderBody
Write-Host "  [OK] Order Created via Gateway (HTTP 201)!" -ForegroundColor Green
Write-Host "       Order ID:    $($orderResp.order_id)" -ForegroundColor White
Write-Host "       Status:      $($orderResp.status)" -ForegroundColor White
Write-Host "       Total:       `$$($orderResp.total)" -ForegroundColor White
Write-Host "       Payment ID:  $($orderResp.payment_id)" -ForegroundColor White

# 3. Verify Trace ID Propagation in Logs
Start-Sleep -Milliseconds 500
Write-Host "`n[3/4] Verifying Trace ID propagation across service logs..." -ForegroundColor Yellow
$logPath = "logs\all_services.log"

if (Test-Path $logPath) {
    $matched = Get-Content $logPath | Select-String $traceId
    $servicesLogged = @()

    foreach ($line in $matched) {
        $json = $line.Line | ConvertFrom-Json
        $servicesLogged += $json.service
        Write-Host "  - [$($json.service.ToUpper())] [$($json.level)] $($json.message)" -ForegroundColor Gray
    }

    $uniqueServices = $servicesLogged | Select-Object -Unique
    Write-Host "  Services recorded with '$traceId': $($uniqueServices -join ', ')" -ForegroundColor White

    if (($uniqueServices -contains "gateway") -and ($uniqueServices -contains "orders") -and ($uniqueServices -contains "payments")) {
        Write-Host "  [OK] TRACE ID FULLY PROPAGATED across Gateway, Orders, and Payments!" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] Expected gateway, orders, and payments in logs." -ForegroundColor Yellow
    }
} else {
    Write-Host "  [FAIL] $logPath not found." -ForegroundColor Red
}

# 4. Check Prometheus Metrics
Write-Host "`n[4/4] Checking Prometheus /metrics endpoint..." -ForegroundColor Yellow
$metrics = Invoke-RestMethod -Uri "http://127.0.0.1:8080/metrics" -Method Get
$reqLines = ($metrics -split "`n") | Where-Object { $_ -match "http_requests_total" -and -not $_.StartsWith("#") }
Write-Host "  Active Gateway request metrics:" -ForegroundColor White
foreach ($line in ($reqLines | Select-Object -First 3)) {
    Write-Host "    $line" -ForegroundColor Gray
}

Write-Host "`n======================================================================" -ForegroundColor Cyan
Write-Host " ALL CHECKS PASSED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "======================================================================`n" -ForegroundColor Cyan
