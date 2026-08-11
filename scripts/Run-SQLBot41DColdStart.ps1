param(
    [ValidateSet('SHADOW', 'CANARY_5', 'CANARY_20', 'SCOPED_STABLE')]
    [string]$Mode = 'SHADOW',
    [string]$Output = 'docs/platformization/sqlbot41/evidence/cold-start.json',
    [string]$SQLBotContainer = 'renewable-sqlbot-41c-runtime-v1-10-0',
    [string]$RedisContainer = 'renewable-data41-redis-1',
    [string]$DatabaseContainer = 'renewable-data41-db-1'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to overwrite cold-start evidence: $outputPath"
}
if (docker ps -q --filter 'name=^/renewable-sqlbot-41d-') {
    throw 'Refusing cold start while a SQLBot 4.1D acceptance task is running'
}

function Get-BusinessSnapshot {
    $sql = @"
SELECT jsonb_build_object(
  'migration', (SELECT version_num FROM alembic_version),
  'charging_sessions', (SELECT COUNT(*) FROM public.fact_charging_session),
  'sales_orders', (SELECT COUNT(*) FROM public.sales_order),
  'active_bindings', (
    SELECT COUNT(*) FROM sqlbot_source_binding_release WHERE status='ACTIVE'
  )
);
"@
    $result = docker exec $DatabaseContainer psql -U alpha -d renewable_p5b `
        -X -A -t -v ON_ERROR_STOP=1 -c $sql
    if ($LASTEXITCODE -ne 0) { throw 'Unable to capture business-data preservation snapshot' }
    return (($result | Out-String).Trim() | ConvertFrom-Json)
}

$startedAt = [DateTimeOffset]::UtcNow
$before = Get-BusinessSnapshot
$containers = @($SQLBotContainer, $RedisContainer)
foreach ($container in $containers) {
    $exists = docker ps -a -q --filter "name=^/$container$"
    if (-not $exists) { throw "Required cold-start container is unavailable: $container" }
    if ((docker inspect $container --format '{{.State.Running}}') -eq 'true') {
        docker stop --time 30 $container | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Unable to stop cold-start container: $container" }
    }
}
foreach ($container in $containers) {
    if ((docker inspect $container --format '{{.State.Running}}') -ne 'false') {
        throw "SQLBot 4.1D related service did not stop completely: $container"
    }
}

& (Join-Path $PSScriptRoot 'Run-SQLBot41DOneClick.ps1') `
    -Mode $Mode `
    -Output $Output
if ($LASTEXITCODE -ne 0) { throw 'One-click restart failed during cold-start acceptance' }

$after = Get-BusinessSnapshot
$report = Get-Content -LiteralPath $outputPath -Raw -Encoding utf8 | ConvertFrom-Json
$preserved = (ConvertTo-Json $before -Compress) -eq (ConvertTo-Json $after -Compress)
$report | Add-Member -NotePropertyName cold_start -NotePropertyValue ([ordered]@{
    status = $(if ($preserved) { 'PASS' } else { 'FAIL' })
    started_at = $startedAt.ToString('o')
    finished_at = [DateTimeOffset]::UtcNow.ToString('o')
    stopped_services = $containers
    services_fully_stopped_before_restart = $true
    persistent_volumes_removed = $false
    business_data_snapshot_preserved = $preserved
    before = $before
    after = $after
})
if (-not $preserved) { $report.status = 'FAIL' }
$report | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $outputPath -Encoding utf8
if (-not $preserved) { throw 'Business-data preservation check failed after cold start' }
Write-Output "SQLBOT41D_COLD_START_EVIDENCE=$outputPath"
