# DataFactory Release Build Script (todo.md S15.2)
#
# Flow:
# 1. Build DataFactoryService.exe
# 2. Health smoke test on service EXE
# 3. Build config-tool.exe
# 4. Copy service to config-tool.exe directory
# 5. Create project/ and template/
# 6. Output size and SHA256 of both EXEs
#
# Usage:
#   cd review3/config-tool
#   .\scripts\build_release.ps1

param(
    [switch]$SkipServiceBuild,
    [switch]$SkipWailsBuild
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigToolDir = Split-Path -Parent $ScriptDir
$Review3Dir = Split-Path -Parent $ConfigToolDir
$BuildBinDir = Join-Path $ConfigToolDir "build\bin"

Write-Host "=== DataFactory Release Build ===" -ForegroundColor Cyan
Write-Host "Config Tool Dir: $ConfigToolDir"
Write-Host "Review3 Dir: $Review3Dir"
Write-Host ""

# 1. Build DataFactoryService.exe
if (-not $SkipServiceBuild) {
    Write-Host "[1/6] Building DataFactoryService.exe..." -ForegroundColor Yellow
    Push-Location $Review3Dir
    try {
        pyinstaller DataFactoryService.spec --noconfirm
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed"
        }
        $ServiceExe = Join-Path $Review3Dir "dist\DataFactoryService.exe"
        if (-not (Test-Path $ServiceExe)) {
            throw "DataFactoryService.exe not generated"
        }
        Write-Host "  DataFactoryService.exe build OK" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
} else {
    Write-Host "[1/6] Skipping DataFactoryService.exe build" -ForegroundColor DarkGray
    $ServiceExe = Join-Path $Review3Dir "dist\DataFactoryService.exe"
}

# 2. Health smoke test (real verification)
Write-Host "[2/6] Service health smoke test..." -ForegroundColor Yellow
if (-not (Test-Path $ServiceExe)) {
    throw "DataFactoryService.exe not found: $ServiceExe"
}

$SmokePort = 18999
$SmokeProcess = $null
try {
    $env:DATAFACTORY_NO_AUTH = "1"
    $SmokeProcess = Start-Process -FilePath $ServiceExe `
        -ArgumentList "--service", "--api-host", "127.0.0.1", "--api-port", $SmokePort `
        -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $env:TEMP "df_smoke_stdout.log") `
        -RedirectStandardError (Join-Path $env:TEMP "df_smoke_stderr.log")

    Write-Host "  Service PID: $($SmokeProcess.Id)"

    # Wait for /api/health ready (up to 15 seconds)
    $HealthOk = $false
    $HealthDetail = ""
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$SmokePort/api/health" -Method GET -TimeoutSec 2
            if ($resp.ok -eq $true -and $resp.serviceState -eq "ready") {
                $HealthOk = $true
                $HealthDetail = "ok=$($resp.ok) protocolVersion=$($resp.protocolVersion) serviceState=$($resp.serviceState) runtimeState=$($resp.runtimeState)"
                break
            }
            $HealthDetail = "ok=$($resp.ok) serviceState=$($resp.serviceState)"
        } catch {
            $HealthDetail = "waiting... ($($_.Exception.Message))"
        }
    }

    if (-not $HealthOk) {
        $stderrLog = ""
        try { $stderrLog = Get-Content (Join-Path $env:TEMP "df_smoke_stderr.log") -Raw -ErrorAction Stop } catch {}
        throw "Health smoke failed: service not ready in 15s. Detail: $HealthDetail`nstderr: $stderrLog"
    }

    Write-Host "  Health OK: $HealthDetail" -ForegroundColor Green

    # Verify protocolVersion
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$SmokePort/api/health" -Method GET -TimeoutSec 2
    if ($resp.protocolVersion -ne 1) {
        throw "protocolVersion mismatch: expected 1, got $($resp.protocolVersion)"
    }

    # Request /api/service/shutdown
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$SmokePort/api/service/shutdown" -Method POST -TimeoutSec 5 -Body '{}' -ContentType 'application/json'
    } catch {
        # shutdown may cause connection drop, ignore
    }

    # Wait for process exit (up to 10 seconds)
    $Exited = $SmokeProcess.WaitForExit(10000)
    if (-not $Exited) {
        Write-Host "  Service did not exit in 10s, killing" -ForegroundColor Red
        $SmokeProcess.Kill()
        $SmokeProcess.WaitForExit(5000)
        throw "Service did not exit within timeout"
    }

    Write-Host "  Service exited normally (exit code: $($SmokeProcess.ExitCode))" -ForegroundColor Green
}
finally {
    if ($SmokeProcess -and -not $SmokeProcess.HasExited) {
        try { $SmokeProcess.Kill() } catch {}
    }
    Remove-Item Env:\DATAFACTORY_NO_AUTH -ErrorAction SilentlyContinue
}

# 3. Build config-tool.exe
if (-not $SkipWailsBuild) {
    Write-Host "[3/6] Building config-tool.exe..." -ForegroundColor Yellow
    Push-Location $ConfigToolDir
    try {
        wails build -skipbindings
        if ($LASTEXITCODE -ne 0) {
            throw "Wails build failed"
        }
        Write-Host "  config-tool.exe build OK" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
} else {
    Write-Host "[3/6] Skipping config-tool.exe build" -ForegroundColor DarkGray
}

# 4. Copy service to config-tool.exe directory
Write-Host "[4/6] Copying DataFactoryService.exe to release dir..." -ForegroundColor Yellow
$TargetServiceExe = Join-Path $BuildBinDir "DataFactoryService.exe"
Copy-Item -Path $ServiceExe -Destination $TargetServiceExe -Force
Write-Host "  Copied to: $TargetServiceExe" -ForegroundColor Green

# 5. Create project/ and template/
Write-Host "[5/6] Creating project/ and template/ dirs..." -ForegroundColor Yellow
$ProjectDir = Join-Path $BuildBinDir "project"
$TemplateDir = Join-Path $BuildBinDir "template"
New-Item -ItemType Directory -Path $ProjectDir -Force | Out-Null
New-Item -ItemType Directory -Path $TemplateDir -Force | Out-Null
Write-Host "  Created: $ProjectDir" -ForegroundColor Green
Write-Host "  Created: $TemplateDir" -ForegroundColor Green

# 6. Output SHA256
Write-Host "[6/6] Computing SHA256..." -ForegroundColor Yellow
$ConfigToolExe = Join-Path $BuildBinDir "config-tool.exe"

Write-Host ""
Write-Host "=== Build Results ===" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $ConfigToolExe) {
    $configToolInfo = Get-Item $ConfigToolExe
    $configToolHash = Get-FileHash $ConfigToolExe -Algorithm SHA256
    $ctSizeMB = [math]::Round($configToolInfo.Length / 1MB, 2)
    Write-Host "config-tool.exe:" -ForegroundColor White
    Write-Host "  Path: $ConfigToolExe"
    Write-Host "  Size: $($configToolInfo.Length) bytes ($ctSizeMB MB)"
    Write-Host "  SHA256: $($configToolHash.Hash)"
} else {
    Write-Host "config-tool.exe: NOT FOUND" -ForegroundColor Red
}

Write-Host ""

if (Test-Path $TargetServiceExe) {
    $serviceInfo = Get-Item $TargetServiceExe
    $serviceHash = Get-FileHash $TargetServiceExe -Algorithm SHA256
    $svcSizeMB = [math]::Round($serviceInfo.Length / 1MB, 2)
    Write-Host "DataFactoryService.exe:" -ForegroundColor White
    Write-Host "  Path: $TargetServiceExe"
    Write-Host "  Size: $($serviceInfo.Length) bytes ($svcSizeMB MB)"
    Write-Host "  SHA256: $($serviceHash.Hash)"
} else {
    Write-Host "DataFactoryService.exe: NOT FOUND" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Release Directory Structure ===" -ForegroundColor Cyan
Write-Host "build/bin/"
Write-Host "  config-tool.exe"
Write-Host "  DataFactoryService.exe"
Write-Host "  project/"
Write-Host "  template/"
Write-Host ""
Write-Host "Build complete!" -ForegroundColor Green
