param(
    [string]$RepoRoot = "F:\github\supcon_tools",
    [string]$BaseUrl = "http://10.10.58.153:31501/",
    [string]$Username = "admin",
    [string]$LocalIp = "10.30.70.77",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $RepoRoot "output\automation_stage2_$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Start-Transcript -Path (Join-Path $outDir "transcript.log") -Force | Out-Null

$env:DATAHUB_BASE_URL = $BaseUrl
$env:DATAHUB_USER = $Username
$env:DATAHUB_TENANT_ID = ""
$env:UA_LOCAL_IP = $LocalIp
$env:PYTHONPATH = $RepoRoot

$steps = [System.Collections.Generic.List[object]]::new()
$fatal = $null

function Run-Step {
    param([string]$Name, [scriptblock]$Action)
    $started = Get-Date
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        $steps.Add([pscustomobject]@{name=$Name; status="PASS"; startedAt=$started.ToString("o"); finishedAt=(Get-Date).ToString("o")})
    } catch {
        $steps.Add([pscustomobject]@{name=$Name; status="FAIL"; startedAt=$started.ToString("o"); finishedAt=(Get-Date).ToString("o"); error=$_.Exception.Message})
        throw
    }
}

try {
    Set-Location $RepoRoot
    if ([string]::IsNullOrWhiteSpace($env:DATAHUB_PASSWORD)) {
        throw "DATAHUB_PASSWORD is not set"
    }

    Run-Step "unit-tests" {
        & $PythonExe -m pytest ua_test_harness/unit_tests -q 2>&1 |
            Tee-Object -FilePath (Join-Path $outDir "pytest.log")
    }

    Run-Step "tpt-datasource-lifecycle" {
        & $PythonExe -m ua_test_harness.tpt_probe `
            --base-url $BaseUrl `
            --username $Username `
            --local-ip $LocalIp `
            --output (Join-Path $outDir "tpt-probe.json") 2>&1 |
            Tee-Object -FilePath (Join-Path $outDir "tpt-probe.log")
    }
} catch {
    $fatal = $_.Exception.Message
    Write-Error $_
} finally {
    $failed = @($steps | Where-Object {$_.status -eq "FAIL"}).Count
    if ($fatal -and $failed -eq 0) { $failed = 1 }
    [pscustomobject]@{
        schemaVersion=1; generatedAt=(Get-Date).ToString("o"); repoRoot=$RepoRoot;
        baseUrl=$BaseUrl; username=$Username; tenantId=""; localIp=$LocalIp;
        passwordPresent=(-not [string]::IsNullOrWhiteSpace($env:DATAHUB_PASSWORD));
        steps=$steps; fatalError=$fatal; status=$(if ($failed -eq 0) {"PASS"} else {"FAIL"})
    } | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir "stage2-result.json")
    Stop-Transcript | Out-Null
    Write-Host "Artifacts: $outDir"
    if ($failed -gt 0) { exit 1 }
}
