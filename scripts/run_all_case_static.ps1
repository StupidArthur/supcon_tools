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
