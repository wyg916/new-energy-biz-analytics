param(
    [string]$ApiImage = 'renewable-sqlbot41-api:test'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$evidence = Join-Path $root 'docs/platformization/sqlbot41/evidence'
$focused = Join-Path $evidence 'sqlbot41d-focused.xml'
$goldenDir = Join-Path $evidence 'golden-41d'
$golden = Join-Path $goldenDir 'dual_engine_golden_contract_v1.json'
$postgres = Join-Path $evidence 'postgres-regression-41d.json'
$data41 = Join-Path $evidence 'data41-regression-41d.json'
$readonly = Join-Path $evidence 'platform-readonly-current-41d.json'
$readonlyNegative = Join-Path $evidence 'readonly-wrapper-negative-41d.json'
$migration = Join-Path $evidence 'migration-current-live-41d.json'
$secretScan = Join-Path $evidence 'secret-scan-41d.json'
foreach ($path in @(
    $focused, $golden, $postgres, $data41, $readonly,
    $readonlyNegative, $migration, $secretScan
)) {
    if (Test-Path -LiteralPath $path) { throw "Refusing to overwrite evidence: $path" }
}
New-Item -ItemType Directory -Path $goldenDir -Force | Out-Null

function Invoke-CopiedContainer {
    param(
        [string]$Name,
        [string[]]$DockerArgs,
        [switch]$CopyRootTests
    )
    if (docker ps -a -q --filter "name=^/$Name$") {
        throw "Acceptance container already exists: $Name"
    }
    $created = $false
    try {
        docker create --name $Name @DockerArgs | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Container creation failed: $Name" }
        $created = $true
        docker cp backend "${Name}:/app/backend" | Out-Null
        docker cp backend/app/. "${Name}:/app/app" | Out-Null
        docker cp deploy "${Name}:/app/deploy" | Out-Null
        docker cp scripts/. "${Name}:/app/scripts" | Out-Null
        if ($CopyRootTests) { docker cp tests/. "${Name}:/app/tests" | Out-Null }
        docker start -a $Name
        $exitCode = [int](docker inspect $Name --format '{{.State.ExitCode}}')
        if ($exitCode -ne 0) { throw "Acceptance container failed: $Name ($exitCode)" }
    } finally {
        if ($created) { docker rm -f $Name | Out-Null }
    }
}

$targets = @(
    'backend/tests/test_sqlbot_adapter.py',
    'backend/tests/test_sqlbot_open_nl2sql_41.py',
    'backend/tests/test_sqlbot_quality_patch.py',
    'backend/tests/test_sqlbot_canary_41d.py',
    'backend/tests/test_engine_router.py',
    'backend/tests/test_query_security.py'
)
$focusedArgs = @(
    '-v', "${evidence}:/evidence",
    '-e', 'APP_ENV=test',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-e', 'AUTO_BOOTSTRAP_DEMO_USERS=false',
    '-w', '/app',
    $ApiImage,
    'python', '-m', 'pytest', '-m', 'no_db'
) + $targets + @(
    '-q', '--tb=short', '--junitxml=/evidence/sqlbot41d-focused.xml'
)
Invoke-CopiedContainer -Name 'renewable-sqlbot-41d-focused' -DockerArgs $focusedArgs

$goldenArgs = @(
    '-v', "${goldenDir}:/evidence",
    '-e', 'APP_ENV=test',
    '-e', 'SIMULATED_DATA_ONLY=true',
    '-w', '/app',
    $ApiImage,
    'python', 'scripts/run_dual_engine_eval.py',
    '--source', '/app/tests/evaluation/nl2sql_dual_engine_v1.json',
    '--output-dir', '/evidence'
)
Invoke-CopiedContainer -Name 'renewable-sqlbot-41d-golden' -DockerArgs $goldenArgs -CopyRootTests

python scripts/run_p5a_full_postgres_regression.py `
    --output-dir "$evidence/postgres-regression-41d-batches" `
    --summary-output $postgres `
    --label p5b-postgres-sqlbot41d `
    --api-image $ApiImage `
    --postgres-image renewable-p5a-postgres:16.14 `
    --network renewable-data41-network `
    --runtime-volume renewable-data41_p4_runtime `
    --container-prefix renewable-p5b-final `
    --expected-tests 478 `
    --max-workers 2
if ($LASTEXITCODE -ne 0) { throw 'Current PostgreSQL regression failed' }

python scripts/run_p5a_full_postgres_regression.py `
    --output-dir "$evidence/data41-regression-41d-batches" `
    --summary-output $data41 `
    --label p5b-postgres-data41d `
    --api-image $ApiImage `
    --postgres-image renewable-p5a-postgres:16.14 `
    --network renewable-data41-network `
    --runtime-volume renewable-data41_p4_runtime `
    --container-prefix renewable-p5b-final `
    --data41-rerun `
    --max-workers 1
if ($LASTEXITCODE -ne 0) { throw 'Current DATA-4.1 regression failed' }

& (Join-Path $PSScriptRoot 'Verify-SQLBot41CReadonly.ps1') `
    -PlatformApiImage $ApiImage `
    -Output 'docs/platformization/sqlbot41/evidence/platform-readonly-current-41d.json'
if ($LASTEXITCODE -ne 0) { throw 'Current readonly live verification failed' }

python scripts/test_sqlbot41c_readonly_wrapper.py --output $readonlyNegative
if ($LASTEXITCODE -ne 0) { throw 'Readonly wrapper negative verification failed' }

python scripts/verify_sqlbot41c2_current_live.py --output $migration
if ($LASTEXITCODE -ne 0) { throw 'Current sqlbot_41c2 migration verification failed' }

python scripts/run_p5a_secret_scan.py `
    --output $secretScan `
    --baseline 8c2300532dc4c02d513df89ea8202c1aa519c6fb `
    --scope SQLBOT-4.1D `
    --cache-volume renewable-data41_trivy_cache
if ($LASTEXITCODE -ne 0) { throw 'SQLBot 4.1D secret scan failed' }

Write-Output "FOCUSED_EVIDENCE=$focused"
Write-Output "GOLDEN_EVIDENCE=$golden"
Write-Output "POSTGRES_EVIDENCE=$postgres"
Write-Output "DATA41_EVIDENCE=$data41"
Write-Output "READONLY_EVIDENCE=$readonly"
Write-Output "MIGRATION_EVIDENCE=$migration"
Write-Output "SECRET_SCAN_EVIDENCE=$secretScan"
