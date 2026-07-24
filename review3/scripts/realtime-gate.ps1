# realtime-gate.ps1
# 统一质量门禁。任一步失败立即停止，返回非 0。

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [string]$Baseline = "8d8474545e2fa8bfa0d1a6e7c2a4b3c178159739",
    [switch]$SkipWailsBuild
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$ArtifactsDir = Join-Path $RepoRoot "artifacts"
if (-not (Test-Path $ArtifactsDir)) { New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null }
$summaryFile = Join-Path $ArtifactsDir "realtime-gate-summary.txt"
$summary = @()
$exitCode = 0

function Log([string]$Text) {
    $script:summary += $Text
    Write-Host $Text
}

function Invoke-GateStep {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "=== $Name ==="

    try {
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE"
        }
        Log "$Name: PASS"
    } catch {
        Log "$Name: FAIL - $($_.Exception.Message)"
        throw
    }
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Log "timestamp: $timestamp"
Log "baseline: $Baseline"

Push-Location $RepoRoot

try {
    $head = git rev-parse HEAD 2>&1
    Log "HEAD: $head"

    # Step 1: Git basic checks
    Invoke-GateStep "Step 1: Git basic checks" {
        git diff --check 2>&1
        if ($LASTEXITCODE -ne 0) { throw "git diff --check failed" }

        git diff --check "$Baseline..HEAD" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "git diff --check baseline..HEAD failed" }

        $todoDiff = git diff --name-only "$Baseline..HEAD" -- todo/ 2>&1
        if ($todoDiff) {
            throw "todo/ files modified in this branch: $todoDiff"
        }

        $todoStaged = git diff --cached --name-only -- todo/ 2>&1
        if ($todoStaged) {
            throw "todo/ files staged: $todoStaged"
        }
    }

    # Step 2: Wails API surface
    Invoke-GateStep "Step 2: Wails API surface" {
        python scripts/verify-wails-bindings.py 2>&1
    }

    # Step 3: Secrets scan
    Invoke-GateStep "Step 3: Secrets scan" {
        python scripts/verify-realtime-secrets.py 2>&1
    }

    # Step 4: Go tests
    Invoke-GateStep "Step 4: Go tests" {
        Push-Location (Join-Path $RepoRoot "config-tool")
        go test -race ./internal/realtime/... ./internal/bindings/... ./internal/app/... -count=1 2>&1
        Pop-Location
    }

    # Step 5: Frontend tests
    $frontendTestOutput = ""
    Invoke-GateStep "Step 5: Frontend tests" {
        Push-Location (Join-Path $RepoRoot "config-tool\frontend")
        $frontendTestOutput = npm test -- --run 2>&1
        Pop-Location
    }
    $testMatch = [regex]::Match(($frontendTestOutput -join "`n"), "Tests\s+(\d+)\s+passed")
    if ($testMatch.Success) {
        Log "  frontend test count: $($testMatch.Groups[1].Value)"
    }

    # Step 6: TypeScript/Vite build
    Invoke-GateStep "Step 6: TypeScript/Vite build" {
        Push-Location (Join-Path $RepoRoot "config-tool\frontend")
        npm run build 2>&1
        Pop-Location
    }

    # Step 7: Python realtime tests
    Invoke-GateStep "Step 7: Python realtime tests" {
        $realtimePythonTests = @(
            "tests/test_engine_api.py",
            "tests/test_alarm_manager.py",
            "tests/test_run_archiver.py",
            "tests/test_force_manager.py",
            "tests/test_realtime_config_compiler.py"
        )
        foreach ($f in $realtimePythonTests) {
            if (-not (Test-Path (Join-Path $RepoRoot $f))) {
                throw "Python test file not found: $f"
            }
        }
        Log "  Python test files: $($realtimePythonTests -join ', ')"
        python -m pytest @realtimePythonTests -q 2>&1
    }

    # Step 8: Auth smoke
    Invoke-GateStep "Step 8: Auth smoke" {
        powershell -ExecutionPolicy Bypass -File scripts/realtime-auth-smoke.ps1 2>&1
    }

    # Step 9: Lifecycle smoke
    Invoke-GateStep "Step 9: Lifecycle smoke" {
        powershell -ExecutionPolicy Bypass -File scripts/realtime-lifecycle-smoke.ps1 2>&1
    }

    # Step 10: Scale test
    Invoke-GateStep "Step 10: Scale test" {
        powershell -ExecutionPolicy Bypass -File scripts/realtime-scale-test.ps1 2>&1
    }

    # Step 11: Wails build
    if (-not $SkipWailsBuild) {
        Invoke-GateStep "Step 11: Wails build" {
            Push-Location (Join-Path $RepoRoot "config-tool")
            wails build 2>&1
            Pop-Location
        }

        # Step 12: Generated binding stability
        Invoke-GateStep "Step 12: Generated binding stability" {
            $bindingDiff = git diff --exit-code -- "config-tool/frontend/wailsjs/go" 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Generated bindings have uncommitted changes after wails build"
            }
        }
    } else {
        Log "Step 11: Wails build (SKIPPED)"
        Log "Step 12: Generated binding stability (SKIPPED)"
    }

    Log ""
    Log "ALL GATES PASSED"
} catch {
    Log ""
    Log "GATE FAILED: $($_.Exception.Message)"
    $exitCode = 1
} finally {
    Pop-Location
    Set-Content -Path $summaryFile -Value ($summary -join "`n") -Encoding UTF8
    Write-Host "wrote $summaryFile"
    exit $exitCode
}
