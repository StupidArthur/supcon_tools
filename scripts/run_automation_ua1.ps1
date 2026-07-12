param(
  [string]$RepoRoot="F:\github\supcon_tools",
  [string]$BaseUrl="http://10.10.58.153:31501/",
  [string]$Username="admin",
  [string]$LocalIp="10.30.70.77",
  [string]$PythonExe="python",
  [int]$MockPort=18964
)
$ErrorActionPreference="Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($env:DATAHUB_PASSWORD)) { throw "DATAHUB_PASSWORD is required" }

$ids=@(
 "UA-1-1-01","UA-1-1-02","UA-1-1-04","UA-1-1-12",
 "UA-1-2-01","UA-1-2-02","UA-1-2-04","UA-1-2-06","UA-1-2-07","UA-1-2-08",
 "UA-1-5-01","UA-1-5-03","UA-1-5-07"
)
$stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$outDir=Join-Path $RepoRoot "output\automation_ua1_$stamp"
$runDir=Join-Path $outDir "run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$configPath=Join-Path $outDir "run-config.json"
$reportPath=Join-Path $runDir "report.json"
$env:DATAHUB_BASE_URL=$BaseUrl
$env:DATAHUB_USER=$Username
$env:DATAHUB_TENANT_ID=""
$env:UA_LOCAL_IP=$LocalIp
$env:PYTHONPATH="$RepoRoot;$RepoRoot\ua_mocker"

@{
 runId="ua1_$stamp"; selectedCaseIds=$ids;
 subject=@{baseUrl=$BaseUrl;tenantId="";username=$Username;password="";token=""};
 localIp=$LocalIp;
 mock=@{controlMode="external-script";endpoints=@{functional="opc.tcp://$LocalIp`:$MockPort/ua_mocker/";reconnect="";performance="";abnormal=""}};
 timeouts=@{pollIntervalMs=500;rtVisibilitySec=90;historyVisibilitySec=120;dsConnectSec=90};
 paths=@{runDir=$runDir;evidenceDir=(Join-Path $runDir "evidence");reportPath=$reportPath};
 note="UA-1 precise datasource batch"
} | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $configPath

$mock=$null
$exitCode=1
try {
 Set-Location $RepoRoot
 & $PythonExe -m pytest ua_test_harness/unit_tests -q 2>&1 | Tee-Object -FilePath (Join-Path $outDir "pytest.log")
 if ($LASTEXITCODE -ne 0) { throw "unit tests failed" }
 $mock=Start-Process -FilePath $PythonExe -ArgumentList @("main.py",(Join-Path $RepoRoot "ua_mocker\smoke_stage3.yaml")) -WorkingDirectory (Join-Path $RepoRoot "ua_mocker") -RedirectStandardOutput (Join-Path $outDir "mock.stdout.log") -RedirectStandardError (Join-Path $outDir "mock.stderr.log") -PassThru
 $ready=$false
 for($i=0;$i -lt 40;$i++){
  Start-Sleep -Milliseconds 500
  if($mock.HasExited){break}
  try{$tcp=[System.Net.Sockets.TcpClient]::new();$tcp.Connect("127.0.0.1",$MockPort);$tcp.Dispose();$ready=$true;break}catch{}
 }
 if(-not $ready){throw "mock not ready"}
 & $PythonExe -m ua_test_harness.cli run --config $configPath --cases ($ids -join ",") 2>&1 | Tee-Object -FilePath (Join-Path $outDir "ua1-cases.log")
 $exitCode=$LASTEXITCODE
} finally {
 if($null -ne $mock -and -not $mock.HasExited){Stop-Process -Id $mock.Id -Force -ErrorAction SilentlyContinue}
 @{generatedAt=(Get-Date).ToString("o");selectedCaseCount=$ids.Count;selectedCases=$ids;reportPath=$reportPath;exitCode=$exitCode;status=$(if($exitCode -eq 0){"PASS"}else{"FAIL"})} | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $outDir "ua1-result.json")
 Write-Host "UA-1 artifacts: $outDir"
}
exit $exitCode
