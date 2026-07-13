param(
    [int]$ChapterTotalSec = 2700,
    [string]$Chapter = "",
    [string]$Cases = "",
    [int]$Limit = 0,
    [switch]$SkipPrereqs,
    [switch]$RerunVerified,
    [string]$BatchLabel = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Get-Location).Path
$env:PYTHONPATH = "$repoRoot;$repoRoot\ua_mocker"

$runnerArgs = @("--out-root", "$repoRoot\output", "--chapter-timeout-sec", "$ChapterTotalSec")
if ($Chapter) { $runnerArgs += @("--chapter", $Chapter) }
if ($Cases) { $runnerArgs += @("--cases", $Cases) }
if ($Limit -gt 0) { $runnerArgs += @("--limit", "$Limit") }
if ($SkipPrereqs) { $runnerArgs += "--skip-prereqs" }
if ($RerunVerified) { $runnerArgs += "--rerun-verified" }
if ($BatchLabel) { $runnerArgs += @("--batch-label", $BatchLabel) }

$proc = Start-Process -FilePath python -ArgumentList @("$repoRoot\scripts\run_automation_ua2.py") + $runnerArgs -WorkingDirectory $repoRoot -RedirectStandardOutput "$repoRoot\output\ua2-ps1.stdout.log" -RedirectStandardError "$repoRoot\output\ua2-ps1.stderr.log" -Wait -PassThru -NoNewWindow
$code = $proc.ExitCode

if ($code -eq 124) {
    Write-Host "UA-2 chapter timeout"
}

exit $code
