<#
  Overnight batch runner: all chapters, all STRICT cases (rerun-verified).
  Usage: powershell -File scripts/overnight_run.ps1
  Output: output/overnight-summary.json + per-chapter result files
#>
$ErrorActionPreference = "Continue"
$repoRoot = "F:\github\supcon_tools"
$runner = "$repoRoot\scripts\run_automation_ua2.py"
$outRoot = "$repoRoot\output"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

# Ensure output dir
New-Item -ItemType Directory -Force -Path $outRoot | Out-Null

$chapters = @(
    @{name="UA-1-1"; timeout=1800},
    @{name="UA-1-2"; timeout=1800},
    @{name="UA-1-3"; timeout=1800},
    @{name="UA-1-4"; timeout=2400},
    @{name="UA-1-5"; timeout=1800},
    @{name="UA-1-6"; timeout=2400},
    @{name="UA-2-1"; timeout=3600},
    @{name="UA-2-2"; timeout=3600},
    @{name="UA-2-3"; timeout=2700},
    @{name="UA-2-4"; timeout=2700},
    @{name="UA-2-5"; timeout=2700},
    @{name="UA-3-1"; timeout=2400},
    @{name="UA-3-2"; timeout=2400},
    @{name="UA-3-3"; timeout=2400},
    @{name="UA-3-4"; timeout=2400}
)

$results = @()
$firstRun = $true

foreach ($ch in $chapters) {
    $name = $ch.name
    $timeout = $ch.timeout
    $label = "overnight_${name}_${timestamp}"
    Write-Host "`n========== $name (timeout=${timeout}s) ==========" -ForegroundColor Cyan
    
    $args = @($runner, "--chapter", $name, "--rerun-verified", "--limit", "999", "--batch-label", $label, "--chapter-timeout-sec", $timeout)
    if (-not $firstRun) {
        $args += "--skip-prereqs"
    }
    $firstRun = $false
    
    $startTime = Get-Date
    $logFile = "$outRoot\overnight_${name}_${timestamp}.log"
    
    try {
        $proc = Start-Process -FilePath "python" -ArgumentList $args -NoNewWindow -Wait -PassThru -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
        $exitCode = $proc.ExitCode
    } catch {
        $exitCode = -1
        $_ | Out-File $logFile -Append
    }
    
    $endTime = Get-Date
    $duration = ($endTime - $startTime).TotalSeconds
    
    # Try to find the result JSON
    $resultJson = Get-ChildItem "$outRoot\ua2-result*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $passCount = 0; $failCount = 0; $blockedCount = 0; $errorCount = 0; $observedCount = 0; $totalCases = 0
    
    if ($resultJson) {
        try {
            $data = Get-Content $resultJson.FullName -Raw | ConvertFrom-Json
            $cases = $data.cases
            $totalCases = $cases.Count
            foreach ($c in $cases) {
                switch ($c.status) {
                    "PASS" { $passCount++ }
                    "FAIL" { $failCount++ }
                    "BLOCKED" { $blockedCount++ }
                    "ERROR" { $errorCount++ }
                    "OBSERVED" { $observedCount++ }
                }
            }
        } catch {
            Write-Host "  WARNING: could not parse $($resultJson.Name)" -ForegroundColor Yellow
        }
    }
    
    $summary = @{
        chapter = $name
        exitCode = $exitCode
        durationSec = [math]::Round($duration, 1)
        total = $totalCases
        pass = $passCount
        fail = $failCount
        blocked = $blockedCount
        error = $errorCount
        observed = $observedCount
        logFile = $logFile
    }
    $results += $summary
    
    Write-Host "  exit=$exitCode duration=${duration}s total=$totalCases pass=$passCount fail=$failCount blocked=$blockedCount error=$errorCount observed=$observedCount" -ForegroundColor $(if($exitCode -eq 0){"Green"}else{"Yellow"})
}

# Write summary
$summaryFile = "$outRoot\overnight-summary_${timestamp}.json"
$results | ConvertTo-Json -Depth 3 | Out-File $summaryFile -Encoding UTF8

Write-Host "`n========== SUMMARY ==========" -ForegroundColor Cyan
$totalAll = 0; $passAll = 0; $failAll = 0; $blockedAll = 0; $errorAll = 0; $observedAll = 0
foreach ($r in $results) {
    Write-Host "  $($r.chapter): total=$($r.total) pass=$($r.pass) fail=$($r.fail) blocked=$($r.blocked) error=$($r.error) observed=$($r.observed) exit=$($r.exitCode)"
    $totalAll += $r.total; $passAll += $r.pass; $failAll += $r.fail; $blockedAll += $r.blocked; $errorAll += $r.error; $observedAll += $r.observed
}
Write-Host "`n  GRAND TOTAL: total=$totalAll pass=$passAll fail=$failAll blocked=$blockedAll error=$errorAll observed=$observedAll" -ForegroundColor Green
Write-Host "  Summary: $summaryFile" -ForegroundColor Green
