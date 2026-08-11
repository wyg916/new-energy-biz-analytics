param(
    [string]$Output = 'docs/platformization/sqlbot41/evidence/real-shadow-50-41c2.json',
    [string]$PlatformApiContainer = 'renewable-integration41-core-api-1',
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$RuntimeVolume = 'renewable-data41_p4_runtime',
    [string]$PlatformDatabaseHost = 'renewable-data41-db-1',
    [string]$SQLBotBaseUrl = 'http://host.docker.internal:18082/api/v1',
    [string]$Provider = 'deepseek',
    [string]$Model = 'deepseek-v4-flash'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (-not $outputPath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Evidence output must stay inside the SQLBot worktree'
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to overwrite evidence: $outputPath"
}
if (-not (docker inspect $PlatformApiContainer 2>$null)) {
    throw "Platform runtime container is unavailable: $PlatformApiContainer"
}

$container = 'renewable-sqlbot-41c2-real-shadow-50'
if (docker ps -a -q --filter "name=^/$container$") {
    throw "Acceptance container already exists: $container"
}
$platform = (docker inspect $PlatformApiContainer | ConvertFrom-Json)[0]
$arguments = @(
    'create', '--name', $container,
    '--network', $PlatformNetwork,
    '-v', "${RuntimeVolume}:/run/p4-runtime:ro",
    '-w', '/app'
)
foreach ($entry in $platform.Config.Env) { $arguments += @('-e', $entry) }
$arguments += @(
    '-e', "ACCEPTANCE_POSTGRES_HOST=$PlatformDatabaseHost",
    '-e', 'ACCEPTANCE_POSTGRES_DB=renewable_p5b',
    '-e', 'ACCEPTANCE_TEST_DATABASE_URL_FROM_RUNTIME=true',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-e', 'VAULT_ADDRESS=http://vault:8200',
    '-e', 'VAULT_ENABLED=true',
    '-e', 'VAULT_ROLE_ID_FILE=/run/p4-runtime/vault_role_id',
    '-e', 'VAULT_SECRET_ID_FILE=/run/p4-runtime/vault_secret_id',
    $platform.Config.Image,
    'python', 'scripts/p4_entrypoint.py',
    'python', 'deploy/sqlbot/run_platform_eval.py',
    'python', 'scripts/run_sqlbot_shadow_eval.py',
    '--source', '/app/tests/evaluation/nl2sql_dual_engine_v1.json',
    '--output', '/tmp/real-shadow-50-41c2.json',
    '--sqlbot-base-url', $SQLBotBaseUrl,
    '--timeout-seconds', '12',
    '--provider', $Provider,
    '--model', $Model,
    '--username-credential-ref', 'name://preprod-sqlbot-username',
    '--password-credential-ref', 'name://preprod-sqlbot-password'
)

$created = $false
try {
    docker @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Shadow container creation failed' }
    $created = $true
    docker cp backend/app/. "${container}:/app/app" | Out-Null
    docker cp scripts/. "${container}:/app/scripts" | Out-Null
    docker cp deploy/. "${container}:/app/deploy" | Out-Null
    docker cp tests/. "${container}:/app/tests" | Out-Null
    docker start -a $container
    $exitCode = [int](docker inspect $container --format '{{.State.ExitCode}}')
    if ($exitCode -ne 0) { throw "Real Shadow failed with exit code $exitCode" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
    docker cp "${container}:/tmp/real-shadow-50-41c2.json" $outputPath | Out-Null
    Write-Output "EVIDENCE=$outputPath"
} finally {
    if ($created) { docker rm -f $container | Out-Null }
}
