param(
    [double]$DurationMinutes = 30,
    [double]$IntervalSeconds = 30,
    [string]$Output = 'docs/platformization/sqlbot41/evidence/canary-20-stability.json',
    [string]$AcceptanceContainer = 'renewable-sqlbot-41d-canary20-stability',
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$RuntimeVolume = 'renewable-data41_p4_runtime',
    [string]$RedisDataVolume = 'renewable-data41_p4_redis',
    [string]$RedisContainer = 'renewable-data41-redis-1',
    [string]$VaultContainer = 'renewable-data41-vault-1',
    [string]$PlatformDatabaseHost = 'renewable-data41-db-1',
    [string]$PlatformDatabaseName = 'renewable_p5b',
    [string]$PlatformApiImage = 'renewable-sqlbot41-api:test',
    [string]$SQLBotBaseUrl = 'http://renewable-sqlbot-41c-runtime-v1-10-0:8000/api/v1',
    [string]$SQLBotRuntimeContainer = 'renewable-sqlbot-41c-runtime-v1-10-0',
    [int]$SQLBotHostPort = 18082,
    [string]$SQLBotVolumePrefix = 'renewable-sqlbot41c'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

$dependencyParams = @{
    PlatformNetwork = $PlatformNetwork
    RuntimeVolume = $RuntimeVolume
    RedisDataVolume = $RedisDataVolume
    RedisContainer = $RedisContainer
    SQLBotContainer = $SQLBotRuntimeContainer
    SQLBotHostPort = $SQLBotHostPort
    SQLBotVolumePrefix = $SQLBotVolumePrefix
}
$null = & (Join-Path $PSScriptRoot 'Start-SQLBot41DDependencies.ps1') @dependencyParams
if ($LASTEXITCODE -ne 0) { throw 'SQLBot 4.1D runtime dependencies are not ready' }

$outputPath = if ([System.IO.Path]::IsPathRooted($Output)) {
    [System.IO.Path]::GetFullPath($Output)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $root $Output))
}
$outputDirectory = Split-Path -Parent $outputPath
$outputName = Split-Path -Leaf $outputPath
if (-not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}
if (Test-Path -LiteralPath $outputPath) { throw "Refusing to overwrite evidence: $outputPath" }
if (docker ps -a -q --filter "name=^/$AcceptanceContainer$") {
    throw "Acceptance container already exists: $AcceptanceContainer"
}

$args = @(
    'create', '--name', $AcceptanceContainer,
    '--network', $PlatformNetwork,
    '-v', "${RuntimeVolume}:/run/p4-runtime:ro",
    '--mount', "type=bind,source=$outputDirectory,target=/evidence",
    '-e', 'APP_ENV=test',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-e', 'AUTO_BOOTSTRAP_DEMO_USERS=false',
    '-e', 'VAULT_ENABLED=true',
    '-e', "VAULT_ADDRESS=http://${VaultContainer}:8200",
    '-e', 'VAULT_ROLE_ID_FILE=/run/p4-runtime/vault_role_id',
    '-e', 'VAULT_SECRET_ID_FILE=/run/p4-runtime/vault_secret_id',
    '-e', "ACCEPTANCE_POSTGRES_HOST=$PlatformDatabaseHost",
    '-e', "ACCEPTANCE_POSTGRES_DB=$PlatformDatabaseName",
    '-w', '/app',
    $PlatformApiImage,
    'python', 'scripts/p4_entrypoint.py',
    'python', 'scripts/run_sqlbot_canary_stability.py',
    '--source', '/app/tests/evaluation/nl2sql_dual_engine_v1.json',
    '--output', "/evidence/$outputName",
    '--sqlbot-base-url', $SQLBotBaseUrl,
    '--timeout-seconds', '12',
    '--duration-minutes', $DurationMinutes,
    '--interval-seconds', $IntervalSeconds
)

function Get-SQLBotRuntimeSample {
    param([string]$Phase)

    $stats = docker stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.PIDs}}' $SQLBotRuntimeContainer
    if ($LASTEXITCODE -ne 0 -or -not $stats) {
        throw "Unable to sample SQLBot runtime resources: $SQLBotRuntimeContainer"
    }
    $parts = $stats -split '\|'
    [pscustomobject]@{
        sampled_at = [DateTimeOffset]::UtcNow.ToString('o')
        phase = $Phase
        cpu_percent = [double](($parts[0] -replace '%', '').Trim())
        memory_usage = $parts[1]
        memory_percent = [double](($parts[2] -replace '%', '').Trim())
        pids = [int]$parts[3]
    }
}

$created = $false
try {
    docker @args | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Stability container creation failed' }
    $created = $true
    docker cp backend/app/. "${AcceptanceContainer}:/app/app" | Out-Null
    docker cp scripts/. "${AcceptanceContainer}:/app/scripts" | Out-Null
    docker cp tests/. "${AcceptanceContainer}:/app/tests" | Out-Null

    # This sample is deliberately collected before the acceptance window starts.
    $runtimeSamples = @((Get-SQLBotRuntimeSample -Phase 'pre_window'))
    Write-Output "STABILITY_PRE_WINDOW_SAMPLE=1 CPU_PERCENT=$($runtimeSamples[0].cpu_percent) MEMORY_PERCENT=$($runtimeSamples[0].memory_percent)"
    docker start $AcceptanceContainer | Out-Null
    while ((docker inspect $AcceptanceContainer --format '{{.State.Running}}') -eq 'true') {
        $runtimeSamples += Get-SQLBotRuntimeSample -Phase 'in_window'
        Write-Output "STABILITY_SAMPLE=$($runtimeSamples.Count) CPU_PERCENT=$($runtimeSamples[-1].cpu_percent) MEMORY_PERCENT=$($runtimeSamples[-1].memory_percent)"
        Start-Sleep -Seconds ([Math]::Min(30, [Math]::Max(1, $IntervalSeconds)))
    }
    $exitCode = [int](docker inspect $AcceptanceContainer --format '{{.State.ExitCode}}')
    $memoryGrowthPass = $false
    if (Test-Path -LiteralPath $outputPath) {
        $artifact = Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
        $memoryGrowthPass = (
            $runtimeSamples.Count -gt 1 -and
            $runtimeSamples[-1].memory_percent -le ($runtimeSamples[0].memory_percent + 5.0) -and
            ($runtimeSamples | Measure-Object -Property memory_percent -Maximum).Maximum -le 85.0
        )
        $artifact | Add-Member -NotePropertyName resource_monitor_started_before_window -NotePropertyValue $true
        $artifact | Add-Member -NotePropertyName runtime_container_memory_samples -NotePropertyValue $runtimeSamples
        $artifact.checks | Add-Member -NotePropertyName runtime_memory_growth -NotePropertyValue $memoryGrowthPass
        if (-not $memoryGrowthPass) { $artifact.status = 'FAIL' }
        $artifact | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $outputPath -Encoding utf8
    }
    if ($exitCode -ne 0) { throw "Stability window failed with exit code $exitCode" }
    if (-not $memoryGrowthPass) { throw 'Stability runtime memory growth gate failed' }
    Write-Output "STABILITY_EVIDENCE=$outputPath"
}
finally {
    if ($created) { docker rm -f $AcceptanceContainer | Out-Null }
}
