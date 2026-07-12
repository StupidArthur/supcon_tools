param(
    [string]$RepoRoot = "F:\github\supcon_tools",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $RepoRoot "output\all_case_static_$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Start-Transcript -Path (Join-Path $outDir "transcript.log") -Force | Out-Null

$env:PYTHONPATH = "$RepoRoot;$RepoRoot\ua_mocker"
$steps = [System.Collections.Generic.List[object]]::new()
$fatal = $null

function Run-Captured {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$StdoutPath,
        [string]$StderrPath
    )
    $started = Get-Date
    $process = Start-Process -FilePath $PythonExe `
        -ArgumentList $Arguments `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath `
        -Wait -PassThru
    $status = if ($process.ExitCode -eq 0) { "PASS" } else { "FAIL" }
    $steps.Add([pscustomobject]@{
        name=$Name; status=$status; exitCode=$process.ExitCode;
        startedAt=$started.ToString("o"); finishedAt=(Get-Date).ToString("o")
    })
    if ($process.ExitCode -ne 0) {
        throw "$Name exit code $($process.ExitCode)"
    }
}

try {
    Set-Location $RepoRoot

    Run-Captured `
        -Name "python-compile" `
        -Arguments @("-m", "compileall", "-q", "ua_test_harness", "tpt_api") `
        -StdoutPath (Join-Path $outDir "compile.log") `
        -StderrPath (Join-Path $outDir "compile.stderr.log")

    Run-Captured `
        -Name "python-unit-tests" `
        -Arguments @("-m", "pytest", "ua_test_harness/unit_tests", "-q") `
        -StdoutPath (Join-Path $outDir "pytest.log") `
        -StderrPath (Join-Path $outDir "pytest.stderr.log")

    $catalogPath = Join-Path $outDir "catalog.json"
    Run-Captured `
        -Name "catalog-export" `
        -Arguments @("-m", "ua_test_harness", "catalog", "--output", $catalogPath) `
        -StdoutPath (Join-Path $outDir "catalog.log") `
        -StderrPath (Join-Path $outDir "catalog.stderr.log")

    $catalog = Get-Content -Raw -Encoding UTF8 $catalogPath | ConvertFrom-Json
    $catalogCount = @($catalog.chapters | ForEach-Object { $_.cases } | ForEach-Object { $_ }).Count
    if ($catalogCount -ne 419) {
        throw "catalog case count $catalogCount != 419"
    }
    $catalogIds = @($catalog.chapters | ForEach-Object { $_.cases } | ForEach-Object { $_.id })
    if (@($catalogIds | Sort-Object -Unique).Count -ne 419) {
        throw "catalog contains duplicate case IDs"
    }

    $inventoryPath = Join-Path $outDir "case-inventory.json"
    Run-Captured `
        -Name "case-inventory" `
        -Arguments @(
            "-m", "ua_test_harness.case_inventory",
            "--repo-root", $RepoRoot,
            "--expected-total", "419",
            "--strict-structure",
            "--output", $inventoryPath
        ) `
        -StdoutPath (Join-Path $outDir "case-inventory.log") `
        -StderrPath (Join-Path $outDir "case-inventory.stderr.log")

    $inventory = Get-Content -Raw -Encoding UTF8 $inventoryPath | ConvertFrom-Json
    $summary = $inventory.summary
    if ($summary.documented -ne 419 -or $summary.implemented -ne 419 -or $summary.unimplemented -ne 0) {
        throw "inventory mismatch documented=$($summary.documented) implemented=$($summary.implemented) unimplemented=$($summary.unimplemented)"
    }
    if ($summary.duplicateDocumentIds -ne 0 -or $summary.malformedRows -ne 0 -or $summary.orphanImplementations -ne 0) {
        throw "inventory structural errors: duplicates=$($summary.duplicateDocumentIds) malformed=$($summary.malformedRows) orphans=$($summary.orphanImplementations)"
    }
} catch {
    $fatal = $_.Exception.Message
    Write-Host "All-case static verification failed: $fatal"
} finally {
    $failed = @($steps | Where-Object { $_.status -eq "FAIL" }).Count
    if ($fatal -and $failed -eq 0) { $failed = 1 }

    [pscustomobject]@{
        schemaVersion=1;
        generatedAt=(Get-Date).ToString("o");
        repoRoot=$RepoRoot;
        expectedTotal=419;
        steps=$steps;
        fatalError=$fatal;
        status=$(if ($failed -eq 0) { "PASS" } else { "FAIL" })
    } | ConvertTo-Json -Depth 8 |
        Set-Content -Encoding UTF8 (Join-Path $outDir "all-case-static-result.json")

    Stop-Transcript | Out-Null
    Write-Host "All-case static artifacts: $outDir"
    if ($failed -gt 0) { exit 1 }
}
