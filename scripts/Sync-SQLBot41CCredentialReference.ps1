param(
    [string]$PlatformApiContainer = 'renewable-integration41-core-api-1',
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$RuntimeVolume = 'renewable-data41_p4_runtime',
    [string]$PlatformDatabaseHost = 'renewable-data41-db-1',
    [string]$SQLBotContainer = 'renewable-sqlbot-41c-runtime-v1-10-0',
    [string]$SQLBotBaseUrl = 'http://host.docker.internal:18082/api/v1',
    [string]$Output = 'docs/platformization/sqlbot41/evidence/credential-reference-sync.json'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (-not $outputPath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Evidence output must stay inside the SQLBot worktree'
}
if (Test-Path -LiteralPath $outputPath) { throw "Refusing to overwrite evidence: $outputPath" }
$task = 'renewable-sqlbot-41c-credential-sync'
if (docker ps -a -q --filter "name=^/$task$") {
    throw "Refusing to replace existing task container: $task"
}
$platform = (docker inspect $PlatformApiContainer | ConvertFrom-Json)[0]
$sqlbot = (docker inspect $SQLBotContainer | ConvertFrom-Json)[0]
$bootstrap = $sqlbot.Config.Env | Where-Object { $_ -like 'DEFAULT_PWD=*' } | Select-Object -First 1
if (-not $bootstrap) { throw 'SQLBot migration credential is unavailable' }
$arguments = @(
    'create', '--name', $task,
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
    '-e', 'PRODUCTION_RELEASE_AUTHORIZED=false',
    '-e', 'VAULT_ADDRESS=http://vault:8200',
    '-e', 'VAULT_ENABLED=true',
    '-e', 'VAULT_ROLE_ID_FILE=/run/p4-runtime/vault_role_id',
    '-e', 'VAULT_SECRET_ID_FILE=/run/p4-runtime/vault_secret_id',
    '-e', "SQLBOT_BOOTSTRAP_CURRENT_PASSWORD=$($bootstrap.Substring('DEFAULT_PWD='.Length))",
    $platform.Config.Image,
    'python', 'scripts/p4_entrypoint.py',
    'python', 'deploy/sqlbot/sync_credential_reference_runtime.py',
    '--sqlbot-base-url', $SQLBotBaseUrl,
    '--output', '/tmp/sqlbot41c-credential-reference-sync.json'
)
$created = $false
try {
    docker @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Credential sync task creation failed' }
    $created = $true
    docker cp backend/app/. "${task}:/app/app" | Out-Null
    docker cp scripts/. "${task}:/app/scripts" | Out-Null
    docker cp deploy/. "${task}:/app/deploy" | Out-Null
    docker start -a $task
    $exitCode = [int](docker inspect $task --format '{{.State.ExitCode}}')
    if ($exitCode -ne 0) { throw "Credential sync failed with exit code $exitCode" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
    docker cp "${task}:/tmp/sqlbot41c-credential-reference-sync.json" $outputPath | Out-Null
    Write-Output "EVIDENCE=$outputPath"
} finally {
    if ($created) { docker rm -f $task | Out-Null }
}
