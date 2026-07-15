# Simple overnight runner - no PowerShell wrapper, just raw python calls
$repoRoot = "F:\github\supcon_tools"
$runner = "$repoRoot\scripts\run_automation_ua2.py"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$chapters = @(
    @{name="UA-1-5"; timeout=1800},
    @{name="UA-1-6"; timeout=2400},
    @{name="UA-2-1"; timeout=5400},
    @{name="UA-2-2"; timeout=5400},
    @{name="UA-2-3"; timeout=3600},
    @{name="UA-2-4"; timeout=3600},
    @{name="UA-2-5"; timeout=3600},
    @{name="UA-3-1"; timeout=3600},
    @{name="UA-3-2"; timeout=3600},
    @{name="UA-3-3"; timeout=3600},
    @{name="UA-3-4"; timeout=3600}
)

foreach ($ch in $chapters) {
    $name = $ch.name
    $timeout = $ch.timeout
    Write-Host "`n===== $name =====" -ForegroundColor Cyan
    $log = "$repoRoot\output\batch_${name}_${timestamp}.log"
    $errlog = "$repoRoot\output\batch_${name}_${timestamp}.err"
    
    $startTime = Get-Date
    & python $runner --chapter $name --rerun-verified --limit 999 --skip-prereqs --batch-label "batch_$timestamp" --chapter-timeout-sec $timeout *> $log 2>$errlog
    $exitCode = $LASTEXITCODE
    $duration = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
    
    # Parse result
    $resultJson = Get-ChildItem "$repoRoot\output\ua2-result*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $summary = ""
    if ($resultJson) {
        try {
            $d = Get-Content $resultJson.FullName -Raw | ConvertFrom-Json
            $summary = "pass=$($d.passCount) fail=$($d.failCount) err=$($d.errorCount) blk=$($d.blockedCount)"
        } catch { $summary = "parse-error" }
    }
    
    $line = "$name exit=$exitCode dur=${duration}s $summary"
    Write-Host $line -ForegroundColor $(if($exitCode -eq 0){"Green"}else{"Yellow"})
    Add-Content "$repoRoot\output\batch_summary_${timestamp}.txt" $line
}

Write-Host "`n===== DONE =====" -ForegroundColor Green
Get-Content "$repoRoot\output\batch_summary_${timestamp}.txt"
