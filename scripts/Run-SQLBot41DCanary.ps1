param(
    [ValidateSet('canary-5', 'canary-20', 'scoped-stable')]
    [string]$Stage,
    [string]$SQLBotBaseUrl = 'http://renewable-sqlbot-41c-runtime-v1-10-0:8000/api/v1',
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$RuntimeVolume = 'renewable-data41_p4_runtime',
    [string]$PlatformDatabaseHost = 'renewable-data41-db-1',
    [ValidatePattern('^$|^-[a-z0-9-]+$')]
    [string]$EvidenceSuffix = '',
    [switch]$Probe,
    [switch]$ConsistencyProbe
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$null = & (Join-Path $PSScriptRoot 'Start-SQLBot41DDependencies.ps1') `
    -PlatformNetwork $PlatformNetwork `
    -RuntimeVolume $RuntimeVolume
if ($LASTEXITCODE -ne 0) { throw 'SQLBot 4.1D runtime dependencies are not ready' }
$evidence = Join-Path $root 'docs/platformization/sqlbot41/evidence'
$names = @{
    'canary-5' = @('canary-5-route-events.json', 'canary-5-acceptance.json')
    'canary-20' = @('canary-20-route-events.json', 'canary-20-acceptance.json')
    'scoped-stable' = @('scoped-stable-route-events.json', 'scoped-stable-acceptance.json')
}
$routeName, $acceptanceName = $names[$Stage]
if ($Probe) {
    $routeName = "$Stage-probe-route-events.json"
    $acceptanceName = "$Stage-probe-acceptance.json"
}
if ($ConsistencyProbe) {
    $routeName = "$Stage-consistency-probe-route-events.json"
    $acceptanceName = "$Stage-consistency-probe-acceptance.json"
}
if ($Probe -and $ConsistencyProbe) { throw 'Choose only one probe mode' }
if ($EvidenceSuffix) {
    $routeName = $routeName -replace '\.json$', "$EvidenceSuffix.json"
    $acceptanceName = $acceptanceName -replace '\.json$', "$EvidenceSuffix.json"
}
$routeOutput = Join-Path $evidence $routeName
$acceptanceOutput = Join-Path $evidence $acceptanceName
foreach ($path in @($routeOutput, $acceptanceOutput)) {
    if (Test-Path -LiteralPath $path) { throw "Refusing to overwrite evidence: $path" }
}

$container = "renewable-sqlbot-41d-$Stage"
if (docker ps -a -q --filter "name=^/$container$") {
    throw "Acceptance container already exists: $container"
}
$args = @(
    'create', '--name', $container,
    '--network', $PlatformNetwork,
    '-v', "${RuntimeVolume}:/run/p4-runtime:ro",
    '-v', "${evidence}:/evidence",
    '-e', 'APP_ENV=test',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-e', 'AUTO_BOOTSTRAP_DEMO_USERS=false',
    '-e', 'VAULT_ENABLED=true',
    '-e', 'VAULT_ADDRESS=http://renewable-data41-vault-1:8200',
    '-e', 'VAULT_ROLE_ID_FILE=/run/p4-runtime/vault_role_id',
    '-e', 'VAULT_SECRET_ID_FILE=/run/p4-runtime/vault_secret_id',
    '-e', "ACCEPTANCE_POSTGRES_HOST=$PlatformDatabaseHost",
    '-e', 'ACCEPTANCE_POSTGRES_DB=renewable_p5b',
    '-w', '/app',
    'renewable-sqlbot41-api:test',
    'python', 'scripts/p4_entrypoint.py',
    'python', 'scripts/run_sqlbot_canary_acceptance.py',
    '--stage', $Stage,
    '--source', '/app/tests/evaluation/nl2sql_dual_engine_v1.json',
    '--route-output', "/evidence/$routeName",
    '--acceptance-output', "/evidence/$acceptanceName",
    '--sqlbot-base-url', $SQLBotBaseUrl,
    '--timeout-seconds', '12'
)
if ($Probe) { $args += '--probe' }
if ($ConsistencyProbe) { $args += '--consistency-probe' }
$created = $false
try {
    docker @args | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance container creation failed' }
    $created = $true
    docker cp backend/app/. "${container}:/app/app" | Out-Null
    docker cp scripts/. "${container}:/app/scripts" | Out-Null
    docker cp tests/. "${container}:/app/tests" | Out-Null
    docker start -a $container
    $exitCode = [int](docker inspect $container --format '{{.State.ExitCode}}')
    if ($exitCode -ne 0) { throw "$Stage failed with exit code $exitCode" }
    Write-Output "ROUTE_EVIDENCE=$routeOutput"
    Write-Output "ACCEPTANCE_EVIDENCE=$acceptanceOutput"
} finally {
    if ($created) { docker rm -f $container | Out-Null }
}
