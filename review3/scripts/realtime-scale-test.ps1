# realtime-scale-test.ps1
# 运行 50,000 tag 规模测试，验证 DOM 有界、订阅有界、无全量 payload。

[CmdletBinding()]
param()

# 注意：本脚本不启用 Set-StrictMode -Version Latest。
# 因为 vitest 输出中包含大量 [22m / [32m 等类 ANSI 控制码，
# 与 StrictMode 对未初始化变量的检查容易混淆（同样的 [...]m 字面量
# 在某些上下文会被误判为未定义变量引用）。
# 用 $ErrorActionPreference = "Stop" 替代以实现快速失败。
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
        throw "scale test file not found: $scaleTest"
    }

    Push-Location (Join-Path $RepoRoot "config-tool\frontend")
    $output = npm test -- --run RuntimeTagTable.scale.test.tsx 2>&1
    $code = $LASTEXITCODE
    Pop-Location

    $outputText = $output -join "`n"

    # 去除 ANSI 颜色码（兼容 ESC 前缀和裸 [...]m 两种情况），
    # 让 vitest 的 "Tests N passed" 行可被正则识别。
    # 直接使用 [char]27 作为 char 字面量（PowerShell 5.1 字符转换兼容性最佳实践）
    $escChar = [char]27
    [void]$escChar.ToString()  # 显式 cast 触发类型推断
    $ansiPatternEsc = [string]::new([char[]]@($escChar)) + '\[[0-9;]*m'
    $outputText = [regex]::Replace($outputText, $ansiPatternEsc, "")
    $ansiPatternBare = '\[[0-9;]*m'
    $outputText = [regex]::Replace($outputText, $ansiPatternBare, "")

    if ($code -ne 0) {
        $output | ForEach-Object { Log "  $_" }
        throw "scale test exited with code $code"
    }

    $match = [regex]::Match($outputText, "SCALE_RESULT\s+(.+)")
    if (-not $match.Success) {
        throw "SCALE_RESULT not found in npm test output (test did not print bounded-DOM metrics)"
    }
    Log "SCALE_RESULT $($match.Groups[1].Value)"

    $testMatch = [regex]::Match($outputText, "Tests\s+(\d+)\s+passed")
    if (-not $testMatch.Success) {
        throw "Could not confirm executed test count (no 'Tests N passed' line in output)"
    }
    $testCount = [int]$testMatch.Groups[1].Value
    Log "test count: $testCount"
    if ($testCount -le 0) {
        throw "scale test reported $testCount passing tests"
    }

    $filesMatch = [regex]::Match($outputText, "Test Files\s+(\d+)\s+passed")
    if (-not $filesMatch.Success) {
        throw "Could not confirm test files count (no 'Test Files N passed' line in output)"
    }

    Log "PASS: scale test"
} catch {
    Log "FAIL: $($_.Exception.Message)"
    $exitCode = 1
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
