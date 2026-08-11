param(
    [double]$DurationMinutes = 30,
    [double]$IntervalSeconds = 30,
    [string]$SQLBotBaseUrl = 'http://renewable-sqlbot-41c-runtime-v1-10-0:8000/api/v1',
    [string]$SQLBotRuntimeContainer = 'renewable-sqlbot-41c-runtime-v1-10-0'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$null = & (Join-Path $PSScriptRoot 'Start-SQLBot41DDependencies.ps1')
if ($LASTEXITCODE -ne 0) { throw 'SQLBot 4.1D runtime dependencies are not ready' }
$evidence = Join-Path $root 'docs/platformization/sqlbot41/evidence'
$output = Join-Path $evidence 'canary-20-stability.json'
if (Test-Path -LiteralPath $output) { throw "Refusing to overwrite evidence: $output" }
$container = 'renewable-sqlbot-41d-canary20-stability'
if (docker ps -a -q --filter "name=^/$container$") {
    throw "Acceptance container already exists: $container"
}
$args = @(
    'create', '--name', $container,
    '--network', 'renewable-data41-network',
    '-v', 'renewable-data41_p4_runtime:/run/p4-runtime:ro',
    '-v', "${evidence}:/evidence",
    '-e', 'APP_ENV=test',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-e', 'AUTO_BOOTSTRAP_DEMO_USERS=false',
    '-e', 'VAULT_ENABLED=true',
    '-e', 'VAULT_ADDRESS=http://renewable-data41-vault-1:8200',
    '-e', 'VAULT_ROLE_ID_FILE=/run/p4-runtime/vault_role_id',
    '-e', 'VAULT_SECRET_ID_FILE=/run/p4-runtime/vault_secret_id',
    '-e', 'ACCEPTANCE_POSTGRES_HOST=renewable-data41-db-1',
    '-e', 'ACCEPTANCE_POSTGRES_DB=renewable_p5b',
    '-w', '/app',
    'renewable-sqlbot41-api:test',
    'python', 'scripts/p4_entrypoint.py',
    'python', 'scripts/run_sqlbot_canary_stability.py',
    '--source', '/app/tests/evaluation/nl2sql_dual_engine_v1.json',
    '--output', '/evidence/canary-20-stability.json',
    '--sqlbot-base-url', $SQLBotBaseUrl,
    '--timeout-seconds', '12',
    '--duration-minutes', $DurationMinutes,
    '--interval-seconds', $IntervalSeconds
)
$created = $false
try {
    docker @args | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Stability container creation failed' }
    $created = $true
    docker cp backend/app/. "${container}:/app/app" | Out-Null
    docker cp scripts/. "${container}:/app/scripts" | Out-Null
    docker cp tests/. "${container}:/app/tests" | Out-Null
    $runtimeSamples = @()
    docker start $container | Out-Null
    while ((docker inspect $container --format '{{.State.Running}}') -eq 'true') {
        $stats = docker stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.PIDs}}' $SQLBotRuntimeContainer
        if ($LASTEXITCODE -ne 0 -or -not $stats) {
            throw "Unable to sample SQLBot runtime memory: $SQLBotRuntimeContainer"
        }
        $parts = $stats -split '\|'
        $runtimeSamples += [pscustomobject]@{
            sampled_at = [DateTimeOffset]::UtcNow.ToString('o')
            cpu_percent = [double](($parts[0] -replace '%', '').Trim())
            memory_usage = $parts[1]
            memory_percent = [double](($parts[2] -replace '%', '').Trim())
            pids = [int]$parts[3]
        }
        Write-Output "STABILITY_SAMPLE=$($runtimeSamples.Count) CPU_PERCENT=$($runtimeSamples[-1].cpu_percent) MEMORY_PERCENT=$($runtimeSamples[-1].memory_percent)"
        Start-Sleep -Seconds ([Math]::Min(30, [Math]::Max(1, $IntervalSeconds)))
    }
    $exitCode = [int](docker inspect $container --format '{{.State.ExitCode}}')
    if (Test-Path -LiteralPath $output) {
        $artifact = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
        $memoryGrowthPass = (
            $runtimeSamples.Count -gt 0 -and
            $runtimeSamples[-1].memory_percent -le ($runtimeSamples[0].memory_percent + 5.0) -and
            ($runtimeSamples | Measure-Object -Property memory_percent -Maximum).Maximum -le 85.0
        )
        $artifact | Add-Member -NotePropertyName runtime_container_memory_samples -NotePropertyValue $runtimeSamples
        $artifact.checks | Add-Member -NotePropertyName runtime_memory_growth -NotePropertyValue $memoryGrowthPass
        if (-not $memoryGrowthPass) { $artifact.status = 'FAIL' }
        $artifact | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $output -Encoding utf8
    }
    if ($exitCode -ne 0) { throw "Stability window failed with exit code $exitCode" }
    if (-not $memoryGrowthPass) { throw 'Stability runtime memory growth gate failed' }
    Write-Output "STABILITY_EVIDENCE=$output"
} finally {
    if ($created) { docker rm -f $container | Out-Null }
}
