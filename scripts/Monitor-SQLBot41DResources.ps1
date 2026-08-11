param(
    [string]$AcceptanceContainer = 'renewable-sqlbot-41d-canary20-stability',
    [string]$SQLBotRuntimeContainer = 'renewable-sqlbot-41c-runtime-v1-10-0',
    [string]$Output = 'docs/platformization/sqlbot41/evidence/canary-20-stability-attempt-3-resource-samples.json',
    [int]$IntervalSeconds = 15
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $Output))
if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to overwrite resource evidence: $outputPath"
}
$samples = @()
$startedAt = [DateTimeOffset]::UtcNow
while ((docker inspect $AcceptanceContainer --format '{{.State.Running}}' 2>$null) -eq 'true') {
    $stats = docker stats --no-stream `
        --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.PIDs}}' `
        $SQLBotRuntimeContainer
    if ($LASTEXITCODE -ne 0 -or -not $stats) {
        throw "Unable to sample SQLBot Runtime resources: $SQLBotRuntimeContainer"
    }
    $parts = $stats -split '\|'
    $samples += [ordered]@{
        sampled_at = [DateTimeOffset]::UtcNow.ToString('o')
        cpu_percent = [double](($parts[0] -replace '%', '').Trim())
        memory_usage = $parts[1]
        memory_percent = [double](($parts[2] -replace '%', '').Trim())
        pids = [int]$parts[3]
    }
    Start-Sleep -Seconds ([Math]::Max(1, $IntervalSeconds))
}
$payload = [ordered]@{
    schema_version = '1.0'
    evidence_type = 'sqlbot41d_runtime_resource_samples'
    status = $(if ($samples.Count -gt 0) { 'PASS' } else { 'FAIL' })
    started_at = $startedAt.ToString('o')
    finished_at = [DateTimeOffset]::UtcNow.ToString('o')
    sample_count = $samples.Count
    samples = $samples
    secret_values_persisted = $false
}
$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $outputPath -Encoding utf8
if ($samples.Count -eq 0) { exit 1 }
