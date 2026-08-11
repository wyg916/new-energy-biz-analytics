param(
    [string]$OutputDirectory = 'runtime/integration41full-backend-regression',
    [string]$PlatformNetwork = 'renewable-integration41-full-network',
    [string]$RuntimeVolume = 'renewable-integration41-full_p4_runtime',
    [string]$RedisHost = 'redis',
    [string]$ApiImage = 'renewable-integration41-full-api:4.1.0-integration-full.1',
    [string]$PostgresImage = 'renewable-p5b-postgres:16.14-hardened',
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$output = [IO.Path]::GetFullPath((Join-Path $root $OutputDirectory))
if (-not $output.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Backend regression evidence must stay inside the Full Integration worktree'
}
$junit = Join-Path $output 'backend-full.xml'
$summary = Join-Path $output 'backend-full-summary.json'
if ((Test-Path -LiteralPath $junit) -or (Test-Path -LiteralPath $summary)) {
    throw "Refusing to overwrite backend regression evidence: $output"
}
New-Item -ItemType Directory -Path $output -Force | Out-Null

$dbContainer = 'renewable-integration41-full-regression-db'
$testContainer = 'renewable-integration41-full-regression-tests'
$database = 'integration_41_full_backend_regression'
foreach ($container in @($dbContainer, $testContainer)) {
    if (docker ps -a -q --filter "name=^/$container$") {
        throw "Backend regression container already exists: $container"
    }
}
$null = docker network inspect $PlatformNetwork 2>$null
if ($LASTEXITCODE -ne 0) { throw "Full Integration network is unavailable: $PlatformNetwork" }
$null = docker volume inspect $RuntimeVolume 2>$null
if ($LASTEXITCODE -ne 0) { throw "Governed runtime volume is unavailable: $RuntimeVolume" }

$startedAt = [DateTimeOffset]::UtcNow
$dbCreated = $false
$testCreated = $false
$testExitCode = -1
$copied = $false
try {
    docker create --name $dbContainer `
        --network $PlatformNetwork `
        -v "${RuntimeVolume}:/run/p4-runtime:ro" `
        --tmpfs '/var/lib/postgresql/data:rw,noexec,nosuid,size=4294967296' `
        -e "POSTGRES_DB=$database" `
        -e 'POSTGRES_USER=alpha' `
        -e 'POSTGRES_PASSWORD_FILE=/run/p4-runtime/postgres_password' `
        $PostgresImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Isolated PostgreSQL creation failed' }
    $dbCreated = $true
    docker start $dbContainer | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Isolated PostgreSQL start failed' }
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        docker exec $dbContainer pg_isready -h 127.0.0.1 -U alpha -d $database 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    if ($LASTEXITCODE -ne 0) { throw 'Isolated PostgreSQL readiness timed out' }

    docker create --name $testContainer `
        --network $PlatformNetwork `
        -v "${RuntimeVolume}:/run/p4-runtime:ro" `
        -e 'APP_ENV=test' `
        -e 'AUTO_BOOTSTRAP_DEMO_USERS=true' `
        -e 'SIMULATED_DATA_ONLY=true' `
        -e 'MEMORY_LIFECYCLE_REDIS_ENABLED=false' `
        -e "INTEGRATION41_REDIS_HOST=$RedisHost" `
        -e "ACCEPTANCE_POSTGRES_HOST=$dbContainer" `
        -e "ACCEPTANCE_POSTGRES_DB=$database" `
        -e 'ACCEPTANCE_TEST_DATABASE_URL_FROM_RUNTIME=true' `
        -w '/app' `
        $ApiImage sh scripts/run_integration41full_backend_regression.sh | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Backend regression container creation failed' }
    $testCreated = $true
    $launcherName = (-join @(
        [char]0x4e00,
        [char]0x952e,
        [char]0x542f,
        [char]0x52a8
    )) + '.bat'
    $launcherPath = Join-Path $root $launcherName
    docker cp backend "${testContainer}:/app/backend" | Out-Null
    docker cp $launcherPath "${testContainer}:/app/$launcherName" | Out-Null
    docker cp backend/app/. "${testContainer}:/app/app" | Out-Null
    docker cp deploy "${testContainer}:/app/deploy" | Out-Null
    docker cp scripts/. "${testContainer}:/app/scripts" | Out-Null
    docker cp docs/. "${testContainer}:/app/docs" | Out-Null
    docker cp data/. "${testContainer}:/app/data" | Out-Null
    docker cp samples "${testContainer}:/app/samples" | Out-Null
    docker cp tests/. "${testContainer}:/app/tests" | Out-Null
    docker start -a $testContainer
    $testExitCode = [int](docker inspect $testContainer --format '{{.State.ExitCode}}')
    docker cp "${testContainer}:/tmp/backend-full.xml" $junit | Out-Null
    $copied = $LASTEXITCODE -eq 0
}
finally {
    $testRemoved = if ($testCreated) {
        docker rm -f $testContainer 1>$null 2>$null
        $LASTEXITCODE -eq 0
    }
    else { $true }
    $dbRemoved = if ($dbCreated) {
        docker rm -f $dbContainer 1>$null 2>$null
        $LASTEXITCODE -eq 0
    }
    else { $true }
}

$counts = [ordered]@{ tests = 0; failures = 0; errors = 0; skipped = 0 }
if ($copied) {
    [xml]$document = Get-Content -LiteralPath $junit -Raw
    $suites = if ($document.testsuites) { @($document.testsuites.testsuite) } else { @($document.testsuite) }
    foreach ($suite in $suites) {
        foreach ($key in @('tests', 'failures', 'errors', 'skipped')) {
            $counts[$key] += [int]$suite.$key
        }
    }
}
$passed = (
    $testExitCode -eq 0 -and $copied -and $counts.tests -gt 0 -and
    $counts.failures -eq 0 -and $counts.errors -eq 0 -and $counts.skipped -eq 0 -and
    $testRemoved -and $dbRemoved
)
$payload = [ordered]@{
    evidence_type = 'integration_41_full_backend_regression'
    status = if ($passed) { 'PASS' } else { 'FAIL' }
    started_at = $startedAt.ToString('o')
    finished_at = [DateTimeOffset]::UtcNow.ToString('o')
    command = 'python -m pytest backend/tests -q'
    database = 'isolated tmpfs PostgreSQL 16.14'
    real_redis_lifecycle = $true
    application_image = $ApiImage
    counts = $counts
    test_exit_code = $testExitCode
    junit = 'backend-full.xml'
    temporary_containers_removed = $testRemoved -and $dbRemoved
    persistent_test_volume_created = $false
    main_database_modified = $false
    secret_values_exposed = $false
}
$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summary -Encoding utf8
Write-Output ($payload | ConvertTo-Json -Depth 10)
if (-not $passed) { throw 'Full backend PostgreSQL/Redis regression failed' }
