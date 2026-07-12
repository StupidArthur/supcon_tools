param(
    [int]$ChapterTotalSec = 2700
)

$ErrorActionPreference = "Stop"

$repoRoot = (Get-Location).Path
$env:PYTHONPATH = "$repoRoot;$repoRoot\ua_mocker"

$runnerArgs = @("--out-root", "$repoRoot\output")
$proc = Start-Process -FilePath python -ArgumentList @("$repoRoot\scripts\run_automation_ua2.py") $runnerArgs -WorkingDirectory $repoRoot -RedirectStandardOutput "$repoRoot\output\ua2-ps1.stdout.log" -RedirectStandardError "$repoRoot\output\ua2-ps1.stderr.log" -Wait -PassThru
$code = $proc.ExitCode

if ($code -eq 124) {
    Write-Host "UA-2 chapter timeout"
}

exit $code
