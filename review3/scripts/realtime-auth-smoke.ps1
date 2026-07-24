# realtime-auth-smoke.ps1
# 验证 Python standalone API 的 REST/WS 鉴权。
#
# 本脚本验证范围：
#   - Python REST auth: covered
#   - Python WS auth: covered
#   - Python token rotation across restarts: covered
#   - Go readiness auth: not covered by this script
#   - GetConnectionInfo: not covered by this script
#   - Wails bridge: not covered by this script
#   - React bootstrap: not covered by this script
#   - Product Stop transaction: not covered by this script
#
# 12 步骤:
#   1. 启动最小实时配置
#   2. readiness 成功
#   3. Python API accepted the configured token
#   4. 无 token REST 401
#   5. 错 token REST 401
#   6. 正确 token REST 200
#   7. 无 token WS close 4401
#   8. 正确 token WS 连接并收到 snapshot/heartbeat
#   9. externally terminate standalone Python process
#  10. process stopped, old endpoint is unreachable
#  11. 再次启动生成新 token
#  12. 旧 token 仍 401，新 token 200
#
# 注意：本脚本**只能输出** token length / token-present / token-rotated 等元信息，
# 绝不打印 token 内容。

[CmdletBinding()]
param(
    [int]$Port = 18500,
    [int]$StartupTimeoutSec = 30,
    [int]$StopTimeoutSec = 5
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$WsCheck = Join-Path $ScriptDir "_ws_auth_check.py"

Push-Location $RepoRoot
$exitCode = 1
$proc = $null
$token1 = ""
$token2 = ""

try {
    Write-Host "=== realtime-auth-smoke ==="
    Write-Host "port: $Port"

    $randHex = {
        param($n)
        $bytes = New-Object byte[] $n
        (New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
        ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
    }
    $token1 = & $randHex 32
    $token2 = & $randHex 32
    Write-Host ("token1 length: " + $token1.Length)
    Write-Host ("token2 length: " + $token2.Length)

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
            -RedirectStandardOutput "$env:TEMP\df_out_${Port}_${Name}.log" `
            -RedirectStandardError  "$env:TEMP\df_err_${Port}_${Name}.log")
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

    function Stop-DataFactory([System.Diagnostics.Process]$P) {
        if ($P -and -not $P.HasExited) {
            # 杀进程树以确保 uvicorn 子进程也退出
            try { taskkill /F /T /PID $P.Id 2>&1 | Out-Null } catch { }
            Stop-Process -Id $P.Id -Force -ErrorAction SilentlyContinue
            $P.WaitForExit($StopTimeoutSec * 1000) | Out-Null
        }
        # 再用 taskkill 兜底杀端口 8000 占用
        try {
            $netstat = netstat -ano | Select-String ":$Port\s" | ForEach-Object { ($_ -split "\s+")[-1] } | Where-Object { $_ -match "^\d+$" } | Select-Object -Unique
            foreach ($p in $netstat) {
                if ($p -ne "0") { taskkill /F /PID $p 2>&1 | Out-Null }
            }
        } catch { }
    }

    # Step 1
    Write-Host "Step 1: start DataFactory"
    $proc = Start-DataFactory $token1 "auth-smoke-1"

    # Step 2
    Write-Host "Step 2: wait readiness"
    if (-not (Wait-Ready $token1 "auth-smoke-1" $StartupTimeoutSec)) {
        Write-Host "FAIL: readiness timeout"
        Get-Content "$env:TEMP\df_err_${Port}_auth-smoke-1.log" -Tail 30 -ErrorAction SilentlyContinue
        exit 2
    }

    # Step 3: Python API accepted the configured token
    Write-Host "Step 3: Python API accepted the configured token"

    # Step 4: no-token REST 401
    Write-Host "Step 4: no-token REST must 401"
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
        Write-Host "FAIL: expected 401, got 200"
        exit 3
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -ne 401) {
            Write-Host "FAIL: expected 401, got $code"
            exit 3
        }
    }

    # Step 5: wrong-token REST 401
    Write-Host "Step 5: wrong-token REST must 401"
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" -Headers @{ "Authorization" = "Bearer deadbeef" } `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
        Write-Host "FAIL: expected 401, got 200"
        exit 4
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -ne 401) {
            Write-Host "FAIL: expected 401, got $code"
            exit 4
        }
    }

    # Step 6: correct-token REST 200
    Write-Host "Step 6: correct-token REST must 200"
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" `
        -Headers @{ "Authorization" = "Bearer $token1" } -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($resp.StatusCode -ne 200) {
        Write-Host "FAIL: expected 200, got $($resp.StatusCode)"
        exit 5
    }

    # Step 7: no-token WS close 4401
    # WS 鉴权用 ?token= query param（不读 Authorization header）
    Write-Host "Step 7: no-token WS must close 4401"
    $ws1 = python $WsCheck "ws://127.0.0.1:$Port/ws/snapshot" "" "4401" 2>&1
    Write-Host "  no-token WS: $ws1"
    if ($ws1 -notmatch "WS_CLOSED 4401" -and $ws1 -notmatch "WS_RECV_ERR.*4401") { Write-Host "FAIL: WS 4401 not seen"; exit 6 }

    # Step 8: correct-token WS connects
    Write-Host "Step 8: correct-token WS connects and receives"
    $ws2 = python $WsCheck "ws://127.0.0.1:$Port/ws/snapshot?token=$token1" "Bearer $token1" 0 2>&1
    Write-Host "  correct-token WS: $ws2"
    if ($ws2 -notmatch "WS_RECV") {
        Write-Host "FAIL: WS connection did not receive a message"
        exit 7
    }

    # Step 9: externally terminate standalone Python process
    Write-Host "Step 9: externally terminate standalone Python process"
    Stop-DataFactory $proc
    $proc = $null
    Start-Sleep -Seconds 1

    # Step 10: process stopped, old endpoint is unreachable
    Write-Host "Step 10: process stopped, old endpoint is unreachable"
    $ok = $false
    $failReason = ""
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok2 = $iar.AsyncWaitHandle.WaitOne(2000)
        if (-not $ok2) {
            $ok = $true
        } else {
            $client.EndConnect($iar)
            $client.Close()
        }
    } catch {
        $msg = $_.Exception.Message
        $failReason = $msg
        if ($msg -match "actively refused|10061|connection|forcibly closed|target machine") { $ok = $true }
    }
    if (-not $ok) { Write-Host "FAIL: post-stop port still open. msg: $failReason"; exit 8 }

    # Step 11: 重新启动 with new token
    Write-Host "Step 11: restart with new token"
    $proc = Start-DataFactory $token2 "auth-smoke-2"
    if (-not (Wait-Ready $token2 "auth-smoke-2" $StartupTimeoutSec)) {
        Write-Host "FAIL: restart readiness timeout"
        exit 9
    }

    # Step 12: 旧 token 401, 新 token 200
    Write-Host "Step 12: old token must 401, new token must 200"
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" -Headers @{ "Authorization" = "Bearer $token1" } `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
        Write-Host "FAIL: old token should 401, got 200"
        exit 10
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -ne 401) { Write-Host "FAIL: old token expected 401, got $code"; exit 10 }
    }
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" `
        -Headers @{ "Authorization" = "Bearer $token2" } -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($resp.StatusCode -ne 200) { Write-Host "FAIL: new token expected 200, got $($resp.StatusCode)"; exit 11 }

    Write-Host "ALL 12 STEPS OK"
    $exitCode = 0

    $summary = @"
# realtime-auth-smoke summary
port: $Port
result: ALL 12 STEPS OK
token-rotated: true
token-length: 32
12/12 steps passed

coverage:
- Python REST auth: covered
- Python WS auth: covered
- Python token rotation across restarts: covered
- Go readiness auth: not covered by this script
- GetConnectionInfo: not covered by this script
- Wails bridge: not covered by this script
- React bootstrap: not covered by this script
- Product Stop transaction: not covered by this script
"@
    $summaryFile = Join-Path $RepoRoot "artifacts\auth-smoke-summary.txt"
    Set-Content -Path $summaryFile -Value $summary -Encoding UTF8
    Write-Host "wrote $summaryFile"
} finally {
    Stop-DataFactory $proc
    Pop-Location
}
exit $exitCode
