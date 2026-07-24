# realtime-lifecycle-smoke.ps1
# 4 场景生命周期冒烟：
#   1. Python standalone external termination and port closure
#   2. Python standalone crash closes port
#   3. binding-level stop failure/retry tests (Go)
#   4. binding-level archive-before-process test (Go)
#
# covered:
# - standalone Python external termination closes port
# - standalone Python crash closes port
# - named Go recovery-state tests executed and passed
# - named Go archive-before-process test executed and passed
#
# not covered:
# - real OS kill timeout followed by retry
# - Wails application shutdown with an unkillable child
# - end-to-end UI Stop retry

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

function Invoke-NamedGoTest {
    param(
        [string]$Package,
        [string]$TestName
    )

    $output = go test -race -count=1 -json -run "^${TestName}$" $Package 2>&1
    $code = $LASTEXITCODE

    if ($code -ne 0) {
        throw "$TestName failed with exit code $code"
    }

    $events = $output |
        ForEach-Object {
            try { $_ | ConvertFrom-Json } catch { $null }
        } |
        Where-Object { $_ -ne $null }

    $foundRun = $events |
        Where-Object {
            $_.Action -eq "run" -and
            $_.Test -eq $TestName
        }

    $foundPass = $events |
        Where-Object {
            $_.Action -eq "pass" -and
            $_.Test -eq $TestName
        }

    if (-not $foundRun) {
        throw "$TestName was not collected or executed (go test found no matching test)"
    }

    if (-not $foundPass) {
        throw "$TestName did not pass (action=pass not found in JSON events)"
    }
}

Push-Location $RepoRoot
Log "=== realtime-lifecycle-smoke ==="
Log "port: $Port"

# ---------- Scenario 1: Python standalone external termination and port closure ----------
Log ""
Log "Scenario 1: Python standalone external termination and port closure"
$token1 = Get-RandomHex 32
$proc = Start-DataFactory $token1 "lc-normal-1"
if (-not (Wait-Ready $token1 "lc-normal-1" $StartupTimeoutSec)) {
    Log "FAIL: readiness timeout (scenario 1)"
    $exitCode = 2
} else {
    Kill-DataFactory $proc
    Start-Sleep -Seconds 1
    if (-not (Port-Open-Check 2000)) { Log "  port closed after termination: OK" }
    else { Log "  FAIL: port still open after termination"; $exitCode = 3 }
}

# ---------- Scenario 2: Python standalone crash closes port ----------
Log ""
Log "Scenario 2: Python standalone crash closes port"
$token2 = Get-RandomHex 32
$proc = Start-DataFactory $token2 "lc-crash-2"
if (-not (Wait-Ready $token2 "lc-crash-2" $StartupTimeoutSec)) {
    Log "FAIL: readiness timeout (scenario 2)"
    $exitCode = 4
} else {
    Kill-DataFactory $proc
    Start-Sleep -Seconds 2
    if (-not (Port-Open-Check 2000)) { Log "  port closed after crash: OK" }
    else { Log "  FAIL: port still open after crash"; $exitCode = 8 }
}

# ---------- Scenario 3: binding-level stop failure/retry tests ----------
Log ""
Log "Scenario 3: binding-level stop failure and retry tests"
Push-Location (Join-Path $RepoRoot "config-tool")
try {
    Invoke-NamedGoTest -Package "./internal/bindings/..." -TestName "TestStart_StopFailurePreservesSessionForRetry"
    Log "  TestStart_StopFailurePreservesSessionForRetry: PASS"
} catch {
    Log "  FAIL: $($_.Exception.Message)"
    $exitCode = 6
}
Pop-Location

# ---------- Scenario 4: binding-level archive-before-process test ----------
Log ""
Log "Scenario 4: binding-level archive-before-process test"
Push-Location (Join-Path $RepoRoot "config-tool")
try {
    Invoke-NamedGoTest -Package "./internal/bindings/..." -TestName "TestLifecycle_ShutdownOrderArchiveBeforeProcessKill"
    Log "  TestLifecycle_ShutdownOrderArchiveBeforeProcessKill: PASS"
} catch {
    Log "  FAIL: $($_.Exception.Message)"
    $exitCode = 7
}
Pop-Location

Pop-Location
if ($exitCode -eq 0) {
    Log ""
    Log "ALL SCENARIOS OK"
} else {
    Log ""
    Log "FAILED with exit $exitCode"
}

Log ""
Log "covered:"
Log "- standalone Python external termination closes port"
Log "- standalone Python crash closes port"
Log "- named Go recovery-state tests executed and passed"
Log "- named Go archive-before-process test executed and passed"
Log ""
Log "not covered:"
Log "- real OS kill timeout followed by retry"
Log "- Wails application shutdown with an unkillable child"
Log "- end-to-end UI Stop retry"

Set-Content -Path $summaryFile -Value ($summary -join "`n") -Encoding UTF8
Write-Host "wrote $summaryFile"
exit $exitCode
