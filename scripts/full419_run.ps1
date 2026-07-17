# Full 419 run: UA-2/UA-3 first (need clean baseline), then UA-1
$repoRoot = "F:\github\supcon_tools"
$runner = "$repoRoot\scripts\run_automation_ua2.py"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$chapters = @(
    @{name="UA-2-1"; timeout=7200},
    @{name="UA-2-2"; timeout=5400},
    @{name="UA-2-3"; timeout=3600},
    @{name="UA-2-4"; timeout=3600},
    @{name="UA-2-5"; timeout=3600},
    @{name="UA-3-1"; timeout=3600},
    @{name="UA-3-2"; timeout=3600},
    @{name="UA-3-3"; timeout=3600},
    @{name="UA-3-4"; timeout=3600},
    @{name="UA-3-5"; timeout=3600},
    @{name="UA-3-6"; timeout=3600},
    @{name="UA-1-1"; timeout=2400},
    @{name="UA-1-2"; timeout=2400},
    @{name="UA-1-3"; timeout=2400},
    @{name="UA-1-4"; timeout=3600},
    @{name="UA-1-5"; timeout=2400},
    @{name="UA-1-6"; timeout=3000}
)

$firstRun = $true
foreach ($ch in $chapters) {
    $name = $ch.name
    $timeout = $ch.timeout
    Write-Host "`n===== $name =====" -ForegroundColor Cyan
    
    $startTime = Get-Date
    $args = @($runner, "--chapter", $name, "--rerun-verified", "--include-partial", "--limit", "999", "--batch-label", "full419_$timestamp", "--chapter-timeout-sec", $timeout)
    if (-not $firstRun) { $args += "--skip-prereqs" }
    $firstRun = $false
    
    & python @args *> "$repoRoot\output\full419_${name}_${timestamp}.log"
    $exitCode = $LASTEXITCODE
    $duration = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
    
    $resultJson = Get-ChildItem "$repoRoot\output\ua2-result*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $summary = ""
    if ($resultJson) {
        try {
            $d = Get-Content $resultJson.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $summary = "pass=$($d.passCount) fail=$($d.failCount) err=$($d.errorCount) blk=$($d.blockedCount)"
        } catch { $summary = "parse-error" }
    }
    
    $line = "$name exit=$exitCode dur=${duration}s $summary"
    Write-Host $line -ForegroundColor $(if($exitCode -eq 0){"Green"}else{"Yellow"})
    Add-Content "$repoRoot\output\full419_summary_${timestamp}.txt" $line
}

Write-Host "`n===== DONE =====" -ForegroundColor Green
Get-Content "$repoRoot\output\full419_summary_${timestamp}.txt"
