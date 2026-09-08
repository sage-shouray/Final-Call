<#
.SYNOPSIS
    Run a k6 load test against the local API.

.DESCRIPTION
    k6 runs in Docker so there is nothing to install. Two details, both the same
    ones sonar-scan.ps1 hit: --network host does not work on Docker Desktop for
    Windows, so the container reaches the API through host.docker.internal; and
    the script is piped in on stdin, so `k6 run -` is the command rather than a
    filename.

    Only read paths are exercised. See the note at the top of read-paths.js:
    uploading is a billed Gemini call and, with auto-posting on and no value
    ceiling, a real posting into the customer's SAP ledger.

.EXAMPLE
    .\run.ps1 -Password 'admin-password'
    .\run.ps1 -Password 'x' -Script read-paths.js -Out summary.json
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Password,
    [string]$Email  = 'admin@sagetl.com',
    [string]$Script = 'read-paths.js',
    [string]$BaseUrl = 'http://host.docker.internal:8000',
    [string]$Out
)

$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot $Script
if (-not (Test-Path $path)) { Write-Host "No such script: $path" -ForegroundColor Red; exit 1 }

# Fail here rather than 40 seconds into a ramp with every request refused.
try {
    $null = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 5
} catch {
    Write-Host 'API is not answering on :8000. Start it first:' -ForegroundColor Red
    Write-Host '  cd docparser\apps\api; python -m uvicorn src.main:app --port 8000' -ForegroundColor DarkGray
    exit 1
}

$dockerArgs = @(
    'run', '--rm', '-i',
    '--add-host=host.docker.internal:host-gateway',
    '-e', "BASE_URL=$BaseUrl",
    '-e', "EMAIL=$Email",
    '-e', "PASSWORD=$Password"
)
if ($Out) {
    # Mount the directory so k6 can write the summary back out to the host.
    $mount = ($PSScriptRoot -replace '\\', '/')
    $dockerArgs += @('-v', "${mount}:/out")
}
$dockerArgs += @('grafana/k6', 'run')
# Flags before the '-' so they are not read as arguments to the script itself.
if ($Out) { $dockerArgs += @('--summary-export', "/out/$Out") }
$dockerArgs += '-'

Get-Content $path -Raw | & docker @dockerArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n   OK   all thresholds met" -ForegroundColor Green
} else {
    # k6 exits 99 when the run completed but a threshold was breached, which is
    # a result rather than an error — the p95 is in the output above.
    Write-Host "`n   k6 exited $LASTEXITCODE (99 = a threshold was breached)" -ForegroundColor Yellow
}
