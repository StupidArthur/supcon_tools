param(
    [int]$TimeoutSec = 180
)

$ErrorActionPreference = "Stop"

python -m ua_test_harness.cli run --suite UA-2 --timeout $TimeoutSec
$code = $LASTEXITCODE

if ($code -eq 124) {
    Write-Host "UA-2 timeout"
}

exit $code
