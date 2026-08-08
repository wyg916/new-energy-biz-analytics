[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [ValidateRange(60, 1800)]
    [int]$TimeoutSeconds = 600,
    [string]$EvidencePath = "runtime/p5c-startup-report.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$baseCompose = Join-Path $workspace "deploy/preproduction/compose.yaml"
$overrideCompose = Join-Path $workspace "deploy/production-acceptance/p5b.override.yaml"
$project = "renewable-p5b-gate-closure"
$releaseVersion = "4.0.0-rc.3"
$expectedMigration = "p5_0001"
$businessUrl = "https://p5b.localhost:8446"
$apiHealthUrl = "$businessUrl/api/v1/health"
$apiReadyUrl = "$businessUrl/api/v1/health/ready"
$oidcUrl = "$businessUrl/oidc/realms/chatbi/.well-known/openid-configuration"
$composeArgs = @("compose", "-p", $project, "-f", $baseCompose, "-f", $overrideCompose)
$requiredImages = @(
    "renewable-p5b-api:4.0.0-rc.3",
    "renewable-p5b-web:4.0.0-rc.3",
    "renewable-p5b-postgres:16.14-hardened",
    "renewable-p5b-keycloak:26.7.0-hardened",
    "renewable-p5b-migration:4.0.0-rc.3",
    "renewable-p5b-alert-receiver:4.0.0-rc.3",
    "renewable-p5b-backup:16.14-hardened",
    "hashicorp/vault:2.0.3@sha256:a296a888b118615dc01d5f1a6846e6d4a7277946caaed5b447008fff5fe06b54",
    "redis:7.4.10-alpine@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2",
    "nginx:1.31.3-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752"
)
$startedAt = [DateTimeOffset]::UtcNow
$steps = [System.Collections.Generic.List[object]]::new()
$failure = $null

function Add-StepResult {
    param(
        [string]$Name,
        [string]$Status,
        [DateTimeOffset]$Started,
        [string]$Detail
    )
    $steps.Add([ordered]@{
        name = $Name
        status = $Status
        started_at = $Started.ToString("o")
        finished_at = [DateTimeOffset]::UtcNow.ToString("o")
        elapsed_seconds = [Math]::Round(([DateTimeOffset]::UtcNow - $Started).TotalSeconds, 3)
        detail = $Detail
    })
}

function Invoke-CheckedNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$FailureMessage
    )
    # Windows PowerShell 5 wraps normal native stderr progress as ErrorRecord.
    # Judge native commands by their exit code, not by the stream used by Docker.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($output) { $output | ForEach-Object { Write-Host $_ } }
    if ($exitCode -ne 0) { throw "$FailureMessage (exit=$exitCode)" }
    return @($output | ForEach-Object { "$_" })
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    $stepStarted = [DateTimeOffset]::UtcNow
    Write-Host "[START] $Name"
    try {
        $detail = & $Action
        Add-StepResult -Name $Name -Status "PASS" -Started $stepStarted -Detail (($detail | Out-String).Trim())
        Write-Host "[PASS]  $Name"
    }
    catch {
        Add-StepResult -Name $Name -Status "FAIL" -Started $stepStarted -Detail $_.Exception.Message
        Write-Host "[FAIL]  $Name"
        throw
    }
}

function Wait-Http {
    param([string]$Url)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $null = & curl.exe --silent --show-error --insecure --fail --resolve "p5b.localhost:8446:127.0.0.1" $Url 2>$null
        if ($LASTEXITCODE -eq 0) { return "HTTP reachable: $Url" }
        Start-Sleep -Seconds 2
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "HTTP endpoint did not become ready within $TimeoutSeconds seconds: $Url"
}

function Write-StartupReport {
    param([string]$Status)
    $resolvedEvidence = if ([IO.Path]::IsPathRooted($EvidencePath)) {
        $EvidencePath
    }
    else {
        Join-Path $workspace $EvidencePath
    }
    $evidenceDirectory = Split-Path -Parent $resolvedEvidence
    if (-not (Test-Path -LiteralPath $evidenceDirectory)) {
        New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
    }
    $branch = (& git -C $workspace branch --show-current 2>$null | Out-String).Trim()
    $head = (& git -C $workspace rev-parse HEAD 2>$null | Out-String).Trim()
    $payload = [ordered]@{
        schema_version = "1.0"
        evidence_type = "p5c_cold_start"
        status = $Status
        started_at = $startedAt.ToString("o")
        finished_at = [DateTimeOffset]::UtcNow.ToString("o")
        git = [ordered]@{ branch = $branch; head = $head }
        runtime = [ordered]@{
            compose_project = $project
            release_version = $releaseVersion
            expected_migration_head = $expectedMigration
            sqlbot_runtime = "NOT_INCLUDED_IN_P5B_RC3"
            rag_mode = "KEYWORD_ONLY"
            production_release_authorized = $false
            production_traffic_switched = $false
        }
        data = [ordered]@{
            classification = "simulated"
            period_start = "2025-01-01"
            period_end = "2026-06-30"
            source = "fixed-seed business-rule simulation stored in PostgreSQL"
            run_id_location = "API responses and audit/evidence records"
        }
        urls = [ordered]@{ business = $businessUrl; api_health = $apiHealthUrl; oidc = $oidcUrl }
        required_images = $requiredImages
        steps = $steps
        failure = $failure
        secret_values_recorded = $false
    }
    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $resolvedEvidence -Encoding utf8
    Write-Host "Startup report: $resolvedEvidence"
}

Push-Location $workspace
try {
    Invoke-Step "Docker engine" {
        Invoke-CheckedNative -FilePath "docker" -Arguments @("info", "--format", "{{.ServerVersion}}") -FailureMessage "Docker engine is unavailable"
    }
    Invoke-Step "Compose contract" {
        Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @("config", "--quiet")) -FailureMessage "P5B Compose contract is invalid"
    }
    Invoke-Step "Frozen image inventory" {
        foreach ($image in $requiredImages) {
            Invoke-CheckedNative -FilePath "docker" -Arguments @("image", "inspect", $image, "--format", "{{.Id}}") -FailureMessage "Required P5B image is missing: $image" | Out-Null
        }
        "Validated $($requiredImages.Count) required image references without rebuilding"
    }
    Invoke-Step "P5B services" {
        Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @("up", "-d", "--wait", "--wait-timeout", "$TimeoutSeconds")) -FailureMessage "P5B Compose startup failed"
    }
    Invoke-Step "API health" { Wait-Http -Url $apiHealthUrl }
    Invoke-Step "API readiness" { Wait-Http -Url $apiReadyUrl }
    Invoke-Step "Business web" { Wait-Http -Url $businessUrl }
    Invoke-Step "OIDC discovery" { Wait-Http -Url $oidcUrl }
    Invoke-Step "Migration head" {
        $migration = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @("exec", "-T", "api", "python", "scripts/p4_entrypoint.py", "alembic", "current")) -FailureMessage "Unable to verify Alembic revision"
        $joined = ($migration -join "`n")
        if ($joined -notmatch [regex]::Escape($expectedMigration)) {
            throw "Expected migration $expectedMigration was not reported"
        }
        $joined
    }
    Write-StartupReport -Status "PASS"
    Write-Host ""
    Write-Host "P5B LOCAL RC STARTUP PASSED"
    Write-Host "Web: $businessUrl"
    Write-Host "API: $apiReadyUrl"
    if (-not $NoBrowser) {
        Start-Process $businessUrl
    }
    exit 0
}
catch {
    $failure = [ordered]@{ type = $_.Exception.GetType().Name; message = $_.Exception.Message }
    Write-StartupReport -Status "FAIL"
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}
