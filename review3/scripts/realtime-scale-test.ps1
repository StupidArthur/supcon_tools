# realtime-scale-test.ps1
# 运行 50,000 tag 规模测试，验证 DOM 有界、订阅有界、无全量 payload。

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$ArtifactsDir = Join-Path $RepoRoot "artifacts"
if (-not (Test-Path $ArtifactsDir)) { New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null }
$summaryFile = Join-Path $ArtifactsDir "scale-summary.txt"
$summary = @()
$exitCode = 0

function Log([string]$Text) {
    $script:summary += $Text
    Write-Host $Text
}

try {
    Log "=== realtime-scale-test ==="

    $scaleTest = Join-Path $RepoRoot "config-tool\frontend\src\features\realtime\RuntimeTagTable.scale.test.tsx"
    if (-not (Test-Path $scaleTest)) {
        Log "FAIL: scale test file not found: $scaleTest"
        $exitCode = 1
    } else {
        Push-Location (Join-Path $RepoRoot "config-tool\frontend")
        $output = npm test -- --run RuntimeTagTable.scale.test.tsx 2>&1
        $code = $LASTEXITCODE
        Pop-Location

        $outputText = $output -join "`n"

        if ($code -ne 0) {
            Log "FAIL: scale test exited with code $code"
            $output | ForEach-Object { Log "  $_" }
            $exitCode = 2
        } else {
            $match = [regex]::Match($outputText, "SCALE_RESULT\s+(.+)")
            if ($match.Success) {
                Log "SCALE_RESULT $($match.Groups[1].Value)"
            } else {
                Log "WARN: SCALE_RESULT not found in output"
            }

            $testMatch = [regex]::Match($outputText, "Tests\s+(\d+)\s+passed")
            if ($testMatch.Success) {
                $testCount = [int]$testMatch.Groups[1].Value
                Log "test count: $testCount"
                if ($testCount -le 0) {
                    Log "FAIL: no tests passed"
                    $exitCode = 3
                }
            } else {
                Log "WARN: could not parse test count"
            }

            if ($exitCode -eq 0) { Log "PASS: scale test" }
        }
    }
} catch {
    Log "FAIL: $($_.Exception.Message)"
    $exitCode = 99
} finally {
    if ($exitCode -eq 0) {
        Log ""
        Log "ALL PASSED"
    } else {
        Log ""
        Log "FAILED with exit $exitCode"
    }
    Set-Content -Path $summaryFile -Value ($summary -join "`n") -Encoding UTF8
    Write-Host "wrote $summaryFile"
    exit $exitCode
}
