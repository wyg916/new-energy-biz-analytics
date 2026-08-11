param(
    [ValidateSet('smoke', 'representative', 'golden')]
    [string]$Mode = 'smoke',
    [string]$Output,
    [string]$Source = 'tests/evaluation/nl2sql_dual_engine_v1.json',
    [ValidateSet(1, 2)]
    [int]$Concurrency = 2
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
if (-not $Output) {
    $Output = "docs/platformization/sqlbot41/evidence/sqlbot41b-live-$Mode.json"
}
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (-not $outputPath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output must stay inside the SQLBot worktree'
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to overwrite evidence: $outputPath"
}
$container = "renewable-sqlbot-41b-live-$Mode"
if (docker ps -a --filter "name=^/$container$" --format '{{.Names}}') {
    throw "Acceptance container already exists: $container"
}
$containerOutput = "/tmp/sqlbot41b-live-$Mode.json"
$arguments = @(
    'create', '--name', $container,
    '--network', 'renewable-data41-network',
    '-v', 'renewable-data41_p4_runtime:/run/p4-runtime:ro'
)
# Preserve the current DATA-4.1 preproduction environment so RBAC/ABAC
# bindings are evaluated in their published environment. Values are passed
# directly to Docker and are never written to evidence or echoed.
$currentApi = docker inspect renewable-data41-api-1 | ConvertFrom-Json
foreach ($entry in $currentApi[0].Config.Env) {
    $arguments += @('-e', $entry)
}
$sqlbotSource = docker inspect renewable-sqlbot-p2a-runtime-v1-8-0 | ConvertFrom-Json
$sqlbotPassword = $sqlbotSource[0].Config.Env | Where-Object {
    $_ -like 'DEFAULT_PWD=*'
} | Select-Object -First 1
if (-not $sqlbotPassword) { throw 'Verified SQLBot runtime credential is unavailable' }
$env:SQLBOT_SERVICE_USERNAME = 'admin'
$env:SQLBOT_SERVICE_PASSWORD = $sqlbotPassword.Substring('DEFAULT_PWD='.Length)
$arguments += @(
    '-e', 'SQLBOT_SERVICE_USERNAME',
    '-e', 'SQLBOT_SERVICE_PASSWORD',
    '-e', 'SECRET_ENV_ALLOWLIST=SQLBOT_SERVICE_USERNAME,SQLBOT_SERVICE_PASSWORD',
    '-e', 'ACCEPTANCE_POSTGRES_HOST=renewable-data41-db-1',
    '-e', 'ACCEPTANCE_POSTGRES_DB=renewable_p5b',
    '-e', 'ACCEPTANCE_TEST_DATABASE_URL_FROM_RUNTIME=true',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-w', '/app',
    'renewable-p5a-api:5.0.0-p5a',
    'python', 'scripts/p4_entrypoint.py',
    'python', 'deploy/sqlbot/run_platform_eval.py',
    'python', 'scripts/run_sqlbot_runtime_eval.py',
    '--mode', $Mode,
    '--output', $containerOutput,
    '--sqlbot-base-url', 'http://host.docker.internal:18081/api/v1',
    '--max-attempts', '1',
    '--timeout-seconds', '90',
    '--concurrency', "$Concurrency",
    '--username-credential-ref', 'env://SQLBOT_SERVICE_USERNAME',
    '--password-credential-ref', 'env://SQLBOT_SERVICE_PASSWORD'
)
if ($Mode -ne 'smoke') {
    $arguments += @('--source', "/app/$($Source -replace '\\','/')")
}
$created = $false
try {
    docker @arguments | Out-Null
    $created = $true
    docker cp backend/app/. "${container}:/app/app" | Out-Null
    docker cp scripts/. "${container}:/app/scripts" | Out-Null
    docker cp deploy/. "${container}:/app/deploy" | Out-Null
    docker cp tests/. "${container}:/app/tests" | Out-Null
    docker start -a $container
    $exitCode = [int](docker inspect $container --format '{{.State.ExitCode}}')
    if ($exitCode -ne 0) {
        throw "Live evaluation failed with exit code $exitCode"
    }
    $parent = Split-Path -Parent $outputPath
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    docker cp "${container}:$containerOutput" $outputPath | Out-Null
    Write-Output "EVIDENCE=$outputPath"
} finally {
    if ($created) {
        docker rm -f $container | Out-Null
    }
}
