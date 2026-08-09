param(
    [string]$PlatformApiContainer = 'renewable-integration41-core-api-1',
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$RuntimeVolume = 'renewable-data41_p4_runtime',
    [string]$PlatformDatabaseHost = 'renewable-data41-db-1',
    [string]$Output = 'docs/platformization/sqlbot41/evidence/platform-readonly-current.json'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (-not $outputPath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Evidence output must stay inside the SQLBot worktree'
}
if (Test-Path -LiteralPath $outputPath) { throw "Refusing to overwrite evidence: $outputPath" }
$task = 'renewable-sqlbot-41c-readonly-verify'
if (docker ps -a -q --filter "name=^/$task$") {
    throw "Refusing to replace existing task container: $task"
}
$platform = (docker inspect $PlatformApiContainer | ConvertFrom-Json)[0]
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
    '-e', 'SIMULATED_DATA_ONLY=true',
    $platform.Config.Image,
    'python', 'deploy/sqlbot/run_platform_eval.py',
    'python', 'deploy/sqlbot/verify_platform_readonly_runtime.py',
    '--output', '/tmp/sqlbot41c-platform-readonly.json'
)
$created = $false
try {
    docker @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Readonly verification task creation failed' }
    $created = $true
    docker cp deploy/. "${task}:/app/deploy" | Out-Null
    docker start -a $task
    $exitCode = [int](docker inspect $task --format '{{.State.ExitCode}}')
    if ($exitCode -ne 0) { throw "Readonly verification failed with exit code $exitCode" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
    docker cp "${task}:/tmp/sqlbot41c-platform-readonly.json" $outputPath | Out-Null
    Write-Output "EVIDENCE=$outputPath"
} finally {
    if ($created) { docker rm -f $task | Out-Null }
}
