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
$outDir = Join-Path $RepoRoot "output\automation_stage3_$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Start-Transcript -Path (Join-Path $outDir "transcript.log") -Force | Out-Null

$env:DATAHUB_BASE_URL = $BaseUrl
$env:DATAHUB_USER = $Username
$env:DATAHUB_TENANT_ID = ""
$env:UA_LOCAL_IP = $LocalIp
$env:PYTHONPATH = "$RepoRoot;$RepoRoot\ua_mocker"

$steps = [System.Collections.Generic.List[object]]::new()
$mock = $null
$fatal = $null

function Run-Step {
    param([string]$Name, [scriptblock]$Action)
    $started = Get-Date
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        $steps.Add([pscustomobject]@{
            name=$Name; status="PASS";
            startedAt=$started.ToString("o"); finishedAt=(Get-Date).ToString("o")
        })
    } catch {
        $steps.Add([pscustomobject]@{
            name=$Name; status="FAIL";
            startedAt=$started.ToString("o"); finishedAt=(Get-Date).ToString("o");
            error=$_.Exception.Message
        })
        throw
    }
}

try {
    Set-Location $RepoRoot

    Run-Step "unit-tests" {
        & $PythonExe -m pytest ua_test_harness/unit_tests -q 2>&1 |
            Tee-Object -FilePath (Join-Path $outDir "pytest.log")
    }

    $mockStdout = Join-Path $outDir "mock.stdout.log"
    $mockStderr = Join-Path $outDir "mock.stderr.log"
    $mock = Start-Process -FilePath $PythonExe `
        -ArgumentList @("main.py", (Join-Path $RepoRoot "ua_mocker\smoke.yaml")) `
        -WorkingDirectory (Join-Path $RepoRoot "ua_mocker") `
        -RedirectStandardOutput $mockStdout `
        -RedirectStandardError $mockStderr `
        -PassThru

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if ($mock.HasExited) { break }
        try {
            $tcp = [System.Net.Sockets.TcpClient]::new()
            $tcp.Connect("127.0.0.1", 18960)
            $tcp.Dispose()
            $ready = $true
            break
        } catch { }
    }
    if (-not $ready) { throw "functional mock did not become ready; see mock logs" }

    Run-Step "local-mock-probe" {
        & $PythonExe -m ua_test_harness.mock_probe `
            --endpoint "opc.tcp://127.0.0.1:18960/ua_mocker/" `
            --output (Join-Path $outDir "mock-probe.json") 2>&1 |
            Tee-Object -FilePath (Join-Path $outDir "mock-probe.log")
    }

    Run-Step "tpt-dataflow-probe" {
        & $PythonExe -m ua_test_harness.dataflow_probe `
            --base-url $BaseUrl `
            --username $Username `
            --local-ip $LocalIp `
            --timeout 90 `
            --output (Join-Path $outDir "dataflow-probe.json") 2>&1 |
            Tee-Object -FilePath (Join-Path $outDir "dataflow-probe.log")
    }
} catch {
    $fatal = $_.Exception.Message
    Write-Error $_
} finally {
    if ($null -ne $mock -and -not $mock.HasExited) {
        Stop-Process -Id $mock.Id -Force -ErrorAction SilentlyContinue
        $mock.WaitForExit(5000) | Out-Null
    }

    Get-ChildItem (Join-Path $RepoRoot "ua_mocker") -Filter "ua_mocker_*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 2 |
        Copy-Item -Destination $outDir -Force -ErrorAction SilentlyContinue

    $failed = @($steps | Where-Object {$_.status -eq "FAIL"}).Count
    if ($fatal -and $failed -eq 0) { $failed = 1 }
    [pscustomobject]@{
        schemaVersion=1;
        generatedAt=(Get-Date).ToString("o");
        repoRoot=$RepoRoot;
        baseUrl=$BaseUrl;
        username=$Username;
        tenantId="";
        localIp=$LocalIp;
        passwordPresent=(-not [string]::IsNullOrWhiteSpace($env:DATAHUB_PASSWORD));
        steps=$steps;
        fatalError=$fatal;
        status=$(if ($failed -eq 0) {"PASS"} else {"FAIL"})
    } | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir "stage3-result.json")

    Stop-Transcript | Out-Null
    Write-Host "Stage 3: Artifacts: $outDir"
    if ($failed -gt 0) { exit 1 }
}
