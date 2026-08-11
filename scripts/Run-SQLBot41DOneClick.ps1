param(
    [ValidateSet('SHADOW', 'CANARY_5', 'CANARY_20', 'SCOPED_STABLE')]
    [string]$Mode = $(if ($env:SQLBOT_41D_MODE) { $env:SQLBOT_41D_MODE } else { 'SHADOW' }),
    [string]$Output = $(
        'runtime/sqlbot41d-startup-' +
        [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss') + '.json'
    ),
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$RuntimeVolume = 'renewable-data41_p4_runtime',
    [string]$RedisDataVolume = 'renewable-data41_p4_redis',
    [string]$RedisContainer = 'renewable-data41-redis-1',
    [string]$PlatformApiContainer = 'renewable-integration41-core-api-1',
    [string]$PlatformDatabaseHost = 'renewable-data41-db-1',
    [string]$PlatformApiImage = 'renewable-sqlbot41-api:test',
    [string]$ExpectedRevision = 'sqlbot_41c2',
    [string]$SQLBotContainer = 'renewable-sqlbot-41c-runtime-v1-10-0',
    [int]$SQLBotHostPort = 18082,
    [string]$SQLBotVolumePrefix = 'renewable-sqlbot41c',
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (-not $outputPath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Startup evidence must stay inside the SQLBot worktree'
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to overwrite startup evidence: $outputPath"
}
$credentialSyncOutputPath = Join-Path `
    (Split-Path -Parent $outputPath) `
    (([IO.Path]::GetFileNameWithoutExtension($outputPath)) + '-credential-sync.json')
if (Test-Path -LiteralPath $credentialSyncOutputPath) {
    throw "Refusing to overwrite credential-sync evidence: $credentialSyncOutputPath"
}
if ($Mode -ne 'SHADOW') {
    $requiredScope = @(
        'QUERY_ENGINE_CANARY_TENANTS',
        'QUERY_ENGINE_CANARY_WORKSPACES',
        'QUERY_ENGINE_CANARY_USERS',
        'QUERY_ENGINE_CANARY_SCENARIOS'
    )
    $missingScope = @(
        $requiredScope | Where-Object {
            -not [Environment]::GetEnvironmentVariable($_)
        }
    )
    if ($missingScope.Count -gt 0) {
        throw "Controlled mode requires all four allowlists: $($missingScope -join ', ')"
    }
}

$dependencies = & (Join-Path $PSScriptRoot 'Start-SQLBot41DDependencies.ps1') `
    -PlatformNetwork $PlatformNetwork `
    -RuntimeVolume $RuntimeVolume `
    -RedisDataVolume $RedisDataVolume `
    -RedisContainer $RedisContainer `
    -SQLBotContainer $SQLBotContainer `
    -SQLBotHostPort $SQLBotHostPort `
    -SQLBotVolumePrefix $SQLBotVolumePrefix
if ($LASTEXITCODE -ne 0) { throw 'SQLBot 4.1D dependency startup failed' }

$credentialSyncOutput = $credentialSyncOutputPath.Substring($root.Length).TrimStart('\', '/')
$credentialSync = & (Join-Path $PSScriptRoot 'Sync-SQLBot41CCredentialReference.ps1') `
    -PlatformApiContainer $PlatformApiContainer `
    -PlatformNetwork $PlatformNetwork `
    -RuntimeVolume $RuntimeVolume `
    -PlatformDatabaseHost $PlatformDatabaseHost `
    -SQLBotContainer $SQLBotContainer `
    -SQLBotBaseUrl "http://${SQLBotContainer}:8000/api/v1" `
    -Output $credentialSyncOutput
if ($LASTEXITCODE -ne 0) { throw 'SQLBot governed credential synchronization failed' }
$credentialSyncReport = Get-Content -LiteralPath $credentialSyncOutputPath -Raw -Encoding utf8 |
    ConvertFrom-Json
if ($credentialSyncReport.status -ne 'PASS') {
    throw "SQLBot governed credential synchronization did not pass: $($credentialSyncReport.status)"
}

function Wait-Http {
    param([string]$Url, [string[]]$ExtraArguments = @())
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & curl.exe --silent --insecure --fail @ExtraArguments $Url 1>$null 2>$null
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($exitCode -eq 0) { return $true }
        Start-Sleep -Seconds 2
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    return $false
}

$runtimeReady = Wait-Http -Url "http://127.0.0.1:${SQLBotHostPort}/"
$apiReady = Wait-Http `
    -Url 'https://p5b.localhost:8446/api/v1/health/ready' `
    -ExtraArguments @('--resolve', 'p5b.localhost:8446:127.0.0.1')
if (-not $runtimeReady -or -not $apiReady) {
    throw "Startup HTTP readiness failed (runtime=$runtimeReady api=$apiReady)"
}

$evidenceDirectory = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Force -Path $evidenceDirectory | Out-Null
$task = 'renewable-sqlbot-41d-startup-readiness'
if (docker ps -a -q --filter "name=^/$task$") {
    throw "Startup readiness task container already exists: $task"
}
$arguments = @(
    'create', '--name', $task,
    '--network', $PlatformNetwork,
    '-v', "${RuntimeVolume}:/run/p4-runtime:ro",
    '-v', "${evidenceDirectory}:/evidence",
    '-e', 'APP_ENV=test',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-e', "ACCEPTANCE_POSTGRES_HOST=$PlatformDatabaseHost",
    '-e', 'ACCEPTANCE_POSTGRES_DB=renewable_p5b',
    '-w', '/app',
    $PlatformApiImage,
    'python', 'scripts/p4_entrypoint.py',
    'python', 'scripts/verify_sqlbot41d_startup_readiness.py',
    '--output', "/evidence/$([IO.Path]::GetFileName($outputPath))",
    '--mode', $Mode,
    '--expected-revision', $ExpectedRevision
)
$created = $false
try {
    docker @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Startup readiness container creation failed' }
    $created = $true
    docker cp backend/app/. "${task}:/app/app" | Out-Null
    docker cp scripts/. "${task}:/app/scripts" | Out-Null
    docker start -a $task
    $exitCode = [int](docker inspect $task --format '{{.State.ExitCode}}')
    if ($exitCode -ne 0) { throw "Startup readiness failed with exit code $exitCode" }
    $report = Get-Content -LiteralPath $outputPath -Raw -Encoding utf8 | ConvertFrom-Json
    $report | Add-Member -NotePropertyName sqlbot_runtime_healthy -NotePropertyValue $runtimeReady
    $report | Add-Member -NotePropertyName api_ready -NotePropertyValue $apiReady
    $report | Add-Member -NotePropertyName dependency_startup -NotePropertyValue `
        (($dependencies | Out-String).Trim() | ConvertFrom-Json)
    $report | Add-Member -NotePropertyName credential_sync -NotePropertyValue $credentialSyncReport
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $outputPath -Encoding utf8
    Write-Output "SQLBOT41D_STARTUP_EVIDENCE=$outputPath"
}
finally {
    if ($created) { docker rm -f $task | Out-Null }
}
