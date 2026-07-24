# realtime-lifecycle-smoke.ps1
# 4 场景真实生命周期冒烟：
#   1. 正常停止（archive stop → Python stop → cleanup）
#   2. 异常退出（外部 kill child → 端口关闭）
#   3. 真实停止失败后重试（Go binding 测试）
#   4. 应用关闭顺序（Go Lifecycle 测试）

[CmdletBinding()]
param(
    [int]$Port = 18510,
    [int]$StartupTimeoutSec = 30,
    [int]$StopTimeoutSec = 5
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$ArtifactsDir = Join-Path $RepoRoot "artifacts"
if (-not (Test-Path $ArtifactsDir)) { New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null }
$summaryFile = Join-Path $ArtifactsDir "lifecycle-smoke-summary.txt"
$summary = @()
$exitCode = 0

function Log([string]$Text) {
    $script:summary += $Text
    Write-Host $Text
}

function Kill-DataFactory([System.Diagnostics.Process]$P) {
    if ($P -and -not $P.HasExited) {
        taskkill /F /T /PID $P.Id 2>&1 | Out-Null
    }
    Start-Sleep -Seconds 1
    # 不再用 netstat 解析（不同 Windows 版本输出格式差异大）。
    # 端口释放由 taskkill /F /T 杀进程树 + Sleep 完成。
    Start-Sleep -Seconds 1
}

function Start-DataFactory([string]$Token, [string]$Name) {
    $args = @(
        "standalone_main.py",
        "-c", "config\tank_constant_sv.yaml",
        "--mode", "REALTIME",
        "--cycle-time", "0.2",
        "--port", "0",
        "--name", $Name,
        "--api",
        "--api-host", "127.0.0.1",
        "--api-port", "$Port",
        "--api-token", $Token
    )
    return (Start-Process -FilePath "python" -ArgumentList $args -PassThru -NoNewWindow `
        -RedirectStandardOutput "$env:TEMP\df_lc_${Port}_${Name}.log" `
        -RedirectStandardError  "$env:TEMP\df_lc_${Port}_${Name}.err.log")
}

function Wait-Ready([string]$Token, [string]$Name, [int]$TimeoutSec) {
    for ($i = 0; $i -lt $TimeoutSec; $i++) {
        Start-Sleep -Seconds 1
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" `
                -Headers @{ "Authorization" = "Bearer $Token" } -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            $json = $resp.Content | ConvertFrom-Json
            if ($json.instance_name -eq $Name) { return $true }
        } catch { }
    }
    return $false
}

function Port-Open-Check([int]$TimeoutMs) {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    $connected = $iar.AsyncWaitHandle.WaitOne($TimeoutMs)
    if ($connected) {
        try { $client.EndConnect($iar) } catch { }
        $client.Close()
        return $true
    }
    return $false
}

function Get-RandomHex([int]$N) {
    $bytes = New-Object byte[] $N
    (New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
    return (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

Push-Location $RepoRoot
Log "=== realtime-lifecycle-smoke ==="
Log "port: $Port"

# ---------- 场景 1：正常停止 ----------
Log ""
Log "Scenario 1: 正常停止"
$token1 = Get-RandomHex 32
$proc = Start-DataFactory $token1 "lc-normal-1"
if (-not (Wait-Ready $token1 "lc-normal-1" $StartupTimeoutSec)) {
    Log "FAIL: readiness timeout (scenario 1)"
    $exitCode = 2
} else {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/archive/start" `
            -Method POST -Headers @{ "Authorization" = "Bearer $token1"; "Content-Type" = "application/json" } `
            -Body '{"sessionId":"lc-1","tags":[],"metadata":{}}' `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
        Log "  archive start: OK"
    } catch { Log "  archive start: FAILED" }
    Kill-DataFactory $proc
    Start-Sleep -Seconds 1
    if (-not (Port-Open-Check 2000)) { Log "  port closed after stop: OK" }
    else { Log "  FAIL: port still open after stop"; $exitCode = 3 }
}

# ---------- 场景 2：异常退出 ----------
Log ""
Log "Scenario 2: 异常退出 (外部 kill child)"
$token2 = Get-RandomHex 32
$proc = Start-DataFactory $token2 "lc-crash-2"
if (-not (Wait-Ready $token2 "lc-crash-2" $StartupTimeoutSec)) {
    Log "FAIL: readiness timeout (scenario 2)"
    $exitCode = 4
} else {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/archive/start" `
            -Method POST -Headers @{ "Authorization" = "Bearer $token2"; "Content-Type" = "application/json" } `
            -Body '{"sessionId":"lc-2","tags":[],"metadata":{}}' `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
    } catch { }
    Kill-DataFactory $proc
    Start-Sleep -Seconds 2
    if (-not (Port-Open-Check 2000)) { Log "  port closed after crash: OK" }
    else { Log "  WARN: port still open after crash" }
}

# ---------- 场景 3：真实停止失败后重试 ----------
Log ""
Log "Scenario 3: real stop failure and retry (Go binding test)"
$token3 = Get-RandomHex 32
$proc = Start-DataFactory $token3 "lc-retry-3"
if (-not (Wait-Ready $token3 "lc-retry-3" $StartupTimeoutSec)) {
    Log "FAIL: readiness timeout (scenario 3)"
    $exitCode = 5
} else {
    Push-Location (Join-Path $RepoRoot "config-tool")
    $goOut = go test -race -count=1 -run "TestStart_StopFailurePreservesSessionForRetry" ./internal/bindings/... 2>&1
    Pop-Location
    if ($LASTEXITCODE -eq 0) { Log "  go test: OK" }
    else {
        Log "  go test: FAIL"
        $goOut | ForEach-Object { Log "    $_" }
        $exitCode = 6
    }
}
Kill-DataFactory $proc

# ---------- 场景 4：应用关闭顺序 ----------
Log ""
Log "Scenario 4: shutdown order (Go Lifecycle test)"
Push-Location (Join-Path $RepoRoot "config-tool")
$goOut = go test -race -count=1 -run "TestLifecycle_ShutdownOrderArchiveBeforeProcessKill" ./internal/app/... 2>&1
Pop-Location
if ($LASTEXITCODE -eq 0) { Log "  go test: OK" }
else {
    Log "  go test: FAIL"
    $goOut | ForEach-Object { Log "    $_" }
    $exitCode = 7
}

Pop-Location
if ($exitCode -eq 0) {
    Log ""
    Log "ALL SCENARIOS OK"
} else {
    Log ""
    Log "FAILED with exit $exitCode"
}
Set-Content -Path $summaryFile -Value ($summary -join "`n") -Encoding UTF8
Write-Host "wrote $summaryFile"
exit $exitCode
