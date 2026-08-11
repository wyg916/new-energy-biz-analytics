param(
    [string]$PlatformApiImage = 'renewable-sqlbot41-api:test',
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$RuntimeVolume = 'renewable-data41_p4_runtime',
    [string]$PlatformDatabaseContainer = 'renewable-data41-db-1',
    [string]$PlatformDatabaseHost = 'renewable-data41-db-1',
    [string]$Output = 'docs/platformization/sqlbot41/evidence/platform-readonly-current.json'
)

$ErrorActionPreference = 'Stop'

function Invoke-DockerInspect {
    param([string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $result = docker @Arguments 2>$null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    return [PSCustomObject]@{ Output = $result; ExitCode = $exitCode }
}

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

$imageCheck = Invoke-DockerInspect -Arguments @('image', 'inspect', $PlatformApiImage, '--format', '{{.Id}}')
if ($imageCheck.ExitCode -ne 0 -or -not $imageCheck.Output) {
    throw "[SQLBOT41C_IMAGE_NOT_FOUND] Exact local image is unavailable: $PlatformApiImage"
}
$networkCheck = Invoke-DockerInspect -Arguments @('network', 'inspect', $PlatformNetwork, '--format', '{{.Id}}')
if ($networkCheck.ExitCode -ne 0 -or -not $networkCheck.Output) {
    throw "[SQLBOT41C_NETWORK_NOT_FOUND] Required network is unavailable: $PlatformNetwork"
}
$volumeCheck = Invoke-DockerInspect -Arguments @('volume', 'inspect', $RuntimeVolume, '--format', '{{.Name}}')
if ($volumeCheck.ExitCode -ne 0 -or -not $volumeCheck.Output) {
    throw "[SQLBOT41C_VOLUME_NOT_FOUND] CredentialReference volume is unavailable: $RuntimeVolume"
}
$databaseCheck = Invoke-DockerInspect -Arguments @('inspect', $PlatformDatabaseContainer, '--format', '{{.State.Running}}')
if ($databaseCheck.ExitCode -ne 0 -or $databaseCheck.Output -ne 'true') {
    throw "[SQLBOT41C_DATABASE_UNAVAILABLE] DATA-4.1 PostgreSQL container is unavailable: $PlatformDatabaseContainer"
}
$arguments = @(
    'create', '--pull', 'never', '--name', $task,
    '--network', $PlatformNetwork,
    '-v', "${RuntimeVolume}:/run/p4-runtime:ro",
    '-w', '/app',
    '-e', "ACCEPTANCE_POSTGRES_HOST=$PlatformDatabaseHost",
    '-e', 'ACCEPTANCE_POSTGRES_DB=renewable_p5b',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-e', "SQLBOT41C_EXACT_IMAGE=$PlatformApiImage",
    $PlatformApiImage,
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
    if ($LASTEXITCODE -ne 0) { throw '[SQLBOT41C_DEPLOY_COPY_FAILED] Verification code copy failed' }
    docker start -a $task
    if ($LASTEXITCODE -ne 0) { throw '[SQLBOT41C_TASK_START_FAILED] Readonly verification task failed' }
    $exitCode = [int](docker inspect $task --format '{{.State.ExitCode}}')
    if ($LASTEXITCODE -ne 0) { throw '[SQLBOT41C_TASK_INSPECT_FAILED] Cannot inspect verification task' }
    if ($exitCode -ne 0) { throw "Readonly verification failed with exit code $exitCode" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
    docker cp "${task}:/tmp/sqlbot41c-platform-readonly.json" $outputPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '[SQLBOT41C_EVIDENCE_COPY_FAILED] Verification evidence copy failed' }
    Write-Output "EVIDENCE=$outputPath"
} finally {
    if ($created) { docker rm -f $task | Out-Null }
}
