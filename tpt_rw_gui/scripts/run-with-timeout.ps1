# run-with-timeout.ps1 - Run a command with a timeout.
# Working directory is set to the project root (parent of scripts/).
#
# Usage:
#   powershell -File scripts/run-with-timeout.ps1 -TimeoutSec 300 -Command "go test ./..."
#
# Exit code: the command's exit code, or 124 on timeout.
param(
    [Parameter(Mandatory = $true)]
    [string]$Command,
    [int]$TimeoutSec = 300
)

$ErrorActionPreference = 'Continue'
$projectRoot = Split-Path $PSScriptRoot -Parent

$job = Start-Job -ScriptBlock {
    param($root, $cmd)
    Set-Location -LiteralPath $root
    $output = & cmd /c "$cmd 2>&1" | Out-String
    [PSCustomObject]@{ Output = $output; ExitCode = $LASTEXITCODE }
} -ArgumentList $projectRoot, $Command

if (Wait-Job $job -Timeout $TimeoutSec) {
    $result = Receive-Job $job
    Remove-Job $job -Force
    if ($null -ne $result) {
        Write-Output $result.Output
        exit $result.ExitCode
    }
    exit 1
} else {
    Stop-Job $job -ErrorAction SilentlyContinue
    Remove-Job $job -Force
    Write-Output "ERROR: command timed out after ${TimeoutSec}s: $Command"
    exit 124
}
