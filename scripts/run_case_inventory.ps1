param(
    [string]$RepoRoot = "F:\github\supcon_tools",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $RepoRoot "output\case_inventory_$stamp"
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
    if ($process.ExitCode -ne 0) {
        $steps.Add([pscustomobject]@{
            name=$Name; status="FAIL"; exitCode=$process.ExitCode;
            startedAt=$started.ToString("o"); finishedAt=(Get-Date).ToString("o")
        })
        throw "$Name exit code $($process.ExitCode)"
    }
    $steps.Add([pscustomobject]@{
        name=$Name; status="PASS"; exitCode=0;
        startedAt=$started.ToString("o"); finishedAt=(Get-Date).ToString("o")
    })
}

try {
    Set-Location $RepoRoot

    Run-Captured `
        -Name "python-unit-tests" `
        -Arguments @("-m", "pytest", "ua_test_harness/unit_tests", "-q") `
        -StdoutPath (Join-Path $outDir "pytest.log") `
        -StderrPath (Join-Path $outDir "pytest.stderr.log")

    Run-Captured `
        -Name "case-inventory" `
        -Arguments @(
            "-m", "ua_test_harness.case_inventory",
            "--repo-root", $RepoRoot,
            "--expected-total", "419",
            "--strict-structure",
            "--output", (Join-Path $outDir "case-inventory.json")
        ) `
        -StdoutPath (Join-Path $outDir "case-inventory.log") `
        -StderrPath (Join-Path $outDir "case-inventory.stderr.log")
} catch {
    $fatal = $_.Exception.Message
    Write-Host "Case inventory failed: $fatal"
} finally {
    $failed = @($steps | Where-Object {$_.status -eq "FAIL"}).Count
    if ($fatal -and $failed -eq 0) { $failed = 1 }

    [pscustomobject]@{
        schemaVersion=1;
        generatedAt=(Get-Date).ToString("o");
        repoRoot=$RepoRoot;
        expectedTotal=419;
        steps=$steps;
        fatalError=$fatal;
        status=$(if ($failed -eq 0) {"PASS"} else {"FAIL"})
    } | ConvertTo-Json -Depth 8 |
        Set-Content -Encoding UTF8 (Join-Path $outDir "case-inventory-result.json")

    Stop-Transcript | Out-Null
    Write-Host "Case inventory artifacts: $outDir"
    if ($failed -gt 0) { exit 1 }
}