<#
.SYNOPSIS
    Run the tests, then a SonarQube analysis of both applications.

.DESCRIPTION
    Two details make this a script rather than a command to remember.

    Coverage paths: pytest writes an absolute Windows path into coverage.xml
    (<source>C:\...\apps\api\src</source>), which the scanner -- running inside a
    container that sees the project at /usr/src -- cannot resolve. Every file is
    then reported as uncovered. Rewriting that one element to a relative path
    fixes all of them.

    Networking: --network host does not work on Docker Desktop for Windows, so
    the scanner reaches the server through host.docker.internal. Without it the
    scan appears to run and silently submits nothing.

.EXAMPLE
    .\sonar-scan.ps1
    .\sonar-scan.ps1 -SkipTests    # reuse the existing coverage reports
#>
[CmdletBinding()]
param([switch]$SkipTests)

$ErrorActionPreference = 'Stop'
$root      = $PSScriptRoot
$repoRoot  = Split-Path $root -Parent
$tokenFile = Join-Path $repoRoot '.sonartoken'

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "   OK   $t" -ForegroundColor Green }
function Fail($t) { Write-Host "   FAIL $t" -ForegroundColor Red }

if (-not (Test-Path $tokenFile)) {
    Fail "No token at $tokenFile. Generate one in SonarQube: My Account -> Security -> Generate Token."
    exit 1
}
$token = (Get-Content $tokenFile -Raw).Trim()

Step 'SonarQube server'
try {
    $status = (Invoke-RestMethod 'http://localhost:9000/api/system/status' -TimeoutSec 10).status
    if ($status -ne 'UP') { Fail "Server reports '$status' - wait for it to finish starting."; exit 1 }
    Ok 'UP on :9000'
} catch {
    Fail 'Not reachable on :9000. Start it with:  docker start sonarqube'
    exit 1
}

if (-not $SkipTests) {
    Step 'Backend tests'
    Push-Location (Join-Path $root 'apps\api')
    $env:PYTHONIOENCODING = 'utf-8'
    & python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'Tests failed - fix them before analysing.'; exit 1 }
    Pop-Location
    Ok 'coverage.xml written'

    Step 'Frontend tests'
    Push-Location (Join-Path $root 'apps\web')
    & npm run test:coverage
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'Frontend tests failed.'; exit 1 }
    Pop-Location
    Ok 'coverage/lcov.info written'
}

Step 'Coverage paths'
# The scanner sees /usr/src, not this machine's drive letters. Making <source>
# relative to the project root lets it match every filename in the report.
$covPath = Join-Path $root 'apps\api\coverage.xml'
if (Test-Path $covPath) {
    $xml = Get-Content $covPath -Raw
    $fixed = [regex]::Replace($xml, '<source>[^<]*</source>', '<source>apps/api/src</source>')
    if ($fixed -ne $xml) {
        Set-Content $covPath $fixed -Encoding utf8 -NoNewline
        Ok 'rewrote the absolute path in coverage.xml'
    } else { Ok 'already relative' }
} else {
    Fail 'apps/api/coverage.xml missing - run without -SkipTests'
    exit 1
}

Step 'Analysis'
Write-Host '   this takes 10-15 minutes on a first run' -ForegroundColor DarkGray
$mount = ($root -replace '\\', '/')
& docker run --rm `
    -v "${mount}:/usr/src" `
    -e SONAR_HOST_URL='http://host.docker.internal:9000' `
    -e SONAR_TOKEN=$token `
    --add-host=host.docker.internal:host-gateway `
    sonarsource/sonar-scanner-cli

if ($LASTEXITCODE -eq 0) {
    Ok 'submitted - results at http://localhost:9000/dashboard?id=uvira-docparser'
} else {
    Fail "Scanner exited $LASTEXITCODE."
    Write-Host '        "Not authorized" means the token was revoked or regenerated' -ForegroundColor DarkGray
    Write-Host '        after this run began. Reissue one and try again.' -ForegroundColor DarkGray
}
