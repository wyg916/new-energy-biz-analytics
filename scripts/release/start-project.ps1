[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [ValidateRange(60, 1800)]
    [int]$TimeoutSeconds = 1800,
    [string]$EvidencePath = "runtime/integration41full-startup-report.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$baseCompose = Join-Path $workspace "deploy/preproduction/compose.yaml"
$overrideCompose = Join-Path $workspace "deploy/production-acceptance/p5b.override.yaml"
$dataOverrideCompose = Join-Path $workspace "deploy/data41/override.yaml"
$p6OverrideCompose = Join-Path $workspace "deploy/p6/override.yaml"
$fullOverrideCompose = Join-Path $workspace "deploy/integration41full/override.yaml"
$project = "renewable-integration41-full"
$releaseVersion = "4.1.0-integration-full.1"
$expectedMigration = "integration_41_full_0001"
$apiImage = "renewable-integration41-full-api:4.1.0-integration-full.1"
$webImage = "renewable-integration41-full-web:4.1.0-integration-full.1"
$sourceHead = (& git -C $workspace rev-parse HEAD 2>$null | Out-String).Trim()
$businessUrl = "https://p5b.localhost:8446"
$apiHealthUrl = "$businessUrl/api/v1/health"
$apiReadyUrl = "$businessUrl/api/v1/health/ready"
$oidcUrl = "$businessUrl/oidc/realms/chatbi/.well-known/openid-configuration"
$composeArgs = @("compose", "-p", $project, "-f", $baseCompose, "-f", $overrideCompose, "-f", $dataOverrideCompose, "-f", $p6OverrideCompose, "-f", $fullOverrideCompose)
$integrationComposeArgs = @("compose", "-p", "renewable-integration41-core", "-f", $baseCompose, "-f", $overrideCompose, "-f", $dataOverrideCompose)
$p6ComposeArgs = @("compose", "-p", "renewable-p6-business-loop-41", "-f", $baseCompose, "-f", $overrideCompose, "-f", $dataOverrideCompose, "-f", $p6OverrideCompose)
$legacyComposeArgs = @("compose", "-p", "renewable-p5b-gate-closure", "-f", $baseCompose, "-f", $overrideCompose)
$dataComposeArgs = @("compose", "-p", "renewable-data41", "-f", $baseCompose, "-f", $overrideCompose, "-f", $dataOverrideCompose)
$requiredImages = @(
    $apiImage,
    $webImage,
    "renewable-p5b-postgres:16.14-hardened",
    "renewable-p5b-keycloak:26.7.0-hardened",
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

function Test-ImageExists {
    param([string]$Image)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $imageId = (& docker image inspect $Image --format "{{.Id}}" 2>$null | Out-String).Trim()
        return $LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($imageId)
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Test-ImageRevision {
    param([string]$Image)
    if (-not (Test-ImageExists -Image $Image)) { return $false }
    $inspect = (& docker image inspect $Image | Out-String) | ConvertFrom-Json
    $configProperty = $inspect[0].PSObject.Properties['Config']
    if ($null -eq $configProperty) { return $false }
    $labelsProperty = $configProperty.Value.PSObject.Properties['Labels']
    if ($null -eq $labelsProperty -or $null -eq $labelsProperty.Value) { return $false }
    $labels = $labelsProperty.Value
    $revisionProperty = $labels.PSObject.Properties['org.opencontainers.image.revision']
    return $null -ne $revisionProperty -and $revisionProperty.Value -eq $sourceHead
}

function Test-FullApiImageCompatible {
    param([string]$Image)
    if (-not (Test-ImageRevision -Image $Image)) { return $false }
    # Keep this shell program on one line. A Windows PowerShell here-string uses
    # CRLF, and the embedded carriage return can make Alpine sh reject a valid
    # cached image during repeat one-click startup.
    $compatibilityCheck = "test -f /app/alembic/versions/integration_41_full_0001_merge.py && grep -q integration_41_full_0001 /app/alembic/versions/integration_41_full_0001_merge.py"
    & docker run --rm --entrypoint sh $Image -lc $compatibilityCheck 1>$null 2>$null
    return $LASTEXITCODE -eq 0
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
        evidence_type = "integration_41_full_startup"
        status = $Status
        started_at = $startedAt.ToString("o")
        finished_at = [DateTimeOffset]::UtcNow.ToString("o")
        git = [ordered]@{ branch = $branch; head = $head }
        runtime = [ordered]@{
            compose_project = $project
            release_version = $releaseVersion
            expected_migration_head = $expectedMigration
            sqlbot_runtime = "REGISTERED_NOT_ELIGIBLE_ENGINE_DISABLED"
            sqlbot_provider_registration = "PASS"
            sqlbot_open_nl2sql_eligible = $false
            sqlbot_traffic_enabled = $false
            p6_business_loops = @("alerts", "reports", "metric_governance")
            rag_capability = "Governed Hybrid RAG V1"
            rag_mode = "hybrid_bm25_vector_rrf_rerank"
            rag_vector = "deterministic_multilingual_feature_hash_v1"
            rag_dimensions = 256
            pgvector_claimed = $false
            memory_scheduler = "ENABLED"
            memory_scheduler_scenarios = @("charging_ops", "sales_ops")
            query_engine_mode = "DETERMINISTIC_ONLY"
            model_gateway_providers = @("kimi", "mimo", "deepseek")
            production_release_authorized = $false
            production_traffic_switched = $false
        }
        data = [ordered]@{
            classification = "OPEN_SOURCE_DERIVED"
            classification_taxonomy = @(
                "OPEN_SOURCE_REAL_DATA",
                "OPEN_SOURCE_DERIVED",
                "BUSINESS_ASSUMPTION",
                "TEST_FIXTURE"
            )
            period_start = "2020-05-09"
            period_end = "2020-06-09"
            source = "ACN-Data via ORNL OpenEnergyDataPortal; transformed into PostgreSQL core and semantic tables"
            source_dataset_version = "ornl-acn-discovery-2020-v1"
            transformation_version = "data41-acn-transform-v1"
            ingestion_run_id = "DATA41-ACN-ORNL-26-V1"
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
        Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @("config", "--quiet")) -FailureMessage "Full Integration Compose contract is invalid"
    }
    Invoke-Step "Committed source snapshot hashes" {
        $manifestPath = Join-Path $workspace "data/open_source/source_manifest.json"
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
        foreach ($snapshot in $manifest.snapshots) {
            $snapshotPath = Join-Path $workspace $snapshot.snapshot_path
            $actual = (Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $snapshot.snapshot_sha256) {
                throw "Source snapshot hash mismatch: $($snapshot.dataset_code)"
            }
        }
        "Validated $($manifest.snapshots.Count) committed snapshots; no startup download"
    }
    Invoke-Step "Full Integration application images" {
        $actions = @()
        if (-not (Test-FullApiImageCompatible -Image $apiImage)) {
            Invoke-CheckedNative -FilePath "docker" -Arguments @(
                "build", "--file", "backend/Dockerfile", "--label",
                "org.opencontainers.image.revision=$sourceHead", "--tag", $apiImage, "."
            ) -FailureMessage "Full Integration API image build failed" | Out-Null
            $actions += "api=BUILT"
        }
        else { $actions += "api=REUSED" }
        if (-not (Test-ImageRevision -Image $webImage)) {
            Invoke-CheckedNative -FilePath "docker" -Arguments @(
                "build", "--label", "org.opencontainers.image.revision=$sourceHead",
                "--tag", $webImage, "frontend"
            ) -FailureMessage "Full Integration web image build failed" | Out-Null
            $actions += "web=BUILT"
        }
        else { $actions += "web=REUSED" }
        "Application image actions: $($actions -join ', ')"
    }
    Invoke-Step "Required image inventory" {
        foreach ($image in $requiredImages) {
            Invoke-CheckedNative -FilePath "docker" -Arguments @("image", "inspect", $image, "--format", "{{.Id}}") -FailureMessage "Required Full Integration dependency image is missing: $image" | Out-Null
        }
        "Validated $($requiredImages.Count) required image references"
    }
    Invoke-Step "Provider credential references" {
        $ready = @()
        foreach ($alias in @("kimi", "mimo", "deepseek")) {
            Invoke-CheckedNative -FilePath "docker" -Arguments @(
                "run", "--rm", "-v",
                "renewable-integration41-full-provider-credentials:/run/provider-credentials:ro",
                "--entrypoint", "test", $apiImage,
                "-s", "/run/provider-credentials/$alias"
            ) -FailureMessage "Controlled Provider credential reference is unavailable: $alias" | Out-Null
            $ready += "$alias=READY"
        }
        $ready -join ", "
    }
    Invoke-Step "Superseded runtime handoff" {
        Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @("down", "--remove-orphans")) -FailureMessage "Unable to stop the previous Full Integration runtime safely" | Out-Null
        Invoke-CheckedNative -FilePath "docker" -Arguments ($p6ComposeArgs + @("down", "--remove-orphans")) -FailureMessage "Unable to stop the previous P6 runtime safely" | Out-Null
        Invoke-CheckedNative -FilePath "docker" -Arguments ($integrationComposeArgs + @("down", "--remove-orphans")) -FailureMessage "Unable to stop the previous Integration runtime safely" | Out-Null
        Invoke-CheckedNative -FilePath "docker" -Arguments ($dataComposeArgs + @("down", "--remove-orphans")) -FailureMessage "Unable to stop the superseded DATA-4.1 runtime safely" | Out-Null
        Invoke-CheckedNative -FilePath "docker" -Arguments ($legacyComposeArgs + @("down", "--remove-orphans")) -FailureMessage "Unable to stop the superseded P5B runtime safely" | Out-Null
        "Stopped Full Integration, P6, Integration-Core, DATA-4.1 and P5B containers without deleting rollback volumes"
    }
    Invoke-Step "DATA-4.1 standalone runtime handoff" {
        $targets = @(
            [ordered]@{
                name = 'renewable-data41-db-1'
                required_volumes = @('renewable-data41_p4_postgres', 'renewable-data41_p4_runtime')
            },
            [ordered]@{
                name = 'renewable-data41-redis-1'
                required_volumes = @('renewable-data41_p4_redis', 'renewable-data41_p4_runtime')
            },
            [ordered]@{
                name = 'renewable-data41-vault-1'
                required_volumes = @('renewable-data41_p4_vault_rc1', 'renewable-data41_p4_vault_audit')
            }
        )
        $handedOff = @()
        foreach ($target in $targets) {
            $existing = & docker ps -a -q --filter "name=^/$($target.name)$"
            if (-not $existing) { continue }
            $details = (& docker inspect $target.name | Out-String) | ConvertFrom-Json
            $configProperty = $details[0].PSObject.Properties['Config']
            $labelsProperty = if ($null -ne $configProperty) {
                $configProperty.Value.PSObject.Properties['Labels']
            }
            else { $null }
            $labels = if ($null -ne $labelsProperty) { $labelsProperty.Value } else { $null }
            $composeProjectLabel = $null
            if ($null -ne $labels) {
                $composeProjectProperty =
                    $labels.PSObject.Properties['com.docker.compose.project']
                if ($null -ne $composeProjectProperty) {
                    $composeProjectLabel = $composeProjectProperty.Value
                }
            }
            if ($composeProjectLabel -eq $project) { continue }
            $mountNames = @(
                foreach ($mount in @($details[0].Mounts)) {
                    $nameProperty = $mount.PSObject.Properties['Name']
                    if ($null -ne $nameProperty -and $nameProperty.Value) {
                        $nameProperty.Value
                    }
                }
            )
            $missingVolumes = @(
                $target.required_volumes | Where-Object { $mountNames -notcontains $_ }
            )
            if ($missingVolumes.Count -gt 0) {
                throw "Refusing unsafe standalone handoff for $($target.name); missing expected volumes: $($missingVolumes -join ', ')"
            }
            if ($details[0].State.Running) {
                Invoke-CheckedNative -FilePath "docker" -Arguments @(
                    "stop", "--time", "30", $target.name
                ) -FailureMessage "Unable to stop standalone DATA-4.1 service $($target.name)" | Out-Null
            }
            Invoke-CheckedNative -FilePath "docker" -Arguments @(
                "rm", $target.name
            ) -FailureMessage "Unable to remove standalone DATA-4.1 service container $($target.name)" | Out-Null
            $handedOff += $target.name
        }
        if ($handedOff.Count) {
            "Recreated by Compose with named data volumes preserved: $($handedOff -join ', ')"
        }
        else {
            'No standalone DATA-4.1 service handoff was required'
        }
    }
    Invoke-Step "Full Integration services" {
        Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @("up", "-d", "--wait", "--wait-timeout", "$TimeoutSeconds")) -FailureMessage "Full Integration Compose startup failed"
    }
    Invoke-Step "API health" { Wait-Http -Url $apiHealthUrl }
    Invoke-Step "API readiness" { Wait-Http -Url $apiReadyUrl }
    Invoke-Step "Runtime ModelGateway provider calls" {
        $providerProbe = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @(
            "exec", "-T", "api", "python", "scripts/p4_entrypoint.py", "python",
            "scripts/run_runtime_model_gateway_probe.py",
            "--output", "/app/data/preproduction-evidence/runtime-model-gateway-provider-probe.json"
        )) -FailureMessage "Runtime ModelGateway provider probe failed"
        $joined = ($providerProbe -join "`n")
        if ($joined -notmatch '"status": "PASS"') {
            throw "Runtime ModelGateway did not prove all three registered providers"
        }
        $joined
    }
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
    Invoke-Step "Full Integration isolated PostgreSQL migration cycle" {
        $cycle = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @(
              "exec", "-T", "api", "python", "scripts/p4_entrypoint.py", "python",
              "scripts/run_p3_migration_acceptance.py", "--database", "integration_41_full_migration_verify",
              "--rollback-revision", "integration_41_merge_0001",
              "--rollback-via-revision", "data_0001"
          )) -FailureMessage "Full Integration isolated PostgreSQL migration cycle failed"
        $joined = ($cycle -join "`n")
        if ($joined -notmatch '"passed": true' -or $joined -notmatch '"head_revision": "integration_41_full_0001"') {
            throw "Full Integration migration cycle did not prove upgrade, downgrade and re-upgrade"
        }
        $joined
    }
    Invoke-Step "Open-source import and P6 bootstrap gate" {
        $initLogs = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @("logs", "--no-color", "init")) -FailureMessage "Unable to read DATA-4.1 init logs"
        $joined = ($initLogs -join "`n")
        if (
            $joined -notmatch '"status": "PASS"' -or
            $joined -notmatch '"quality_check_fail_count": 0' -or
            $joined -notmatch 'P6 enterprise operating-management closed loops' -or
            $joined -notmatch 'PENDING_GOVERNED_API'
        ) {
            throw "Full init did not report passing DATA quality and P6 readiness"
        }
        $joined
    }
    Invoke-Step "Governed Knowledge Baseline bootstrap" {
        $knowledge = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @(
            "exec", "-T", "api", "python", "scripts/p4_entrypoint.py", "python",
            "scripts/apply_knowledge_baseline_bootstrap.py",
            "--api-base", "http://api:8000/api/v1",
            "--oidc-login-base", "http://oidc:8080/oidc",
            "--output", "/app/data/preproduction-evidence/knowledge-bootstrap.json"
        )) -FailureMessage "Governed Knowledge Baseline bootstrap failed"
        $joined = ($knowledge -join "`n")
        if ($joined -notmatch '"status": "PASS"' -or $joined -notmatch '"principal": "integration.knowledge-bootstrap"') {
            throw "Knowledge bootstrap did not prove the controlled Integration principal"
        }
        $joined
    }
    Invoke-Step "RAG rebuild and index completeness" {
        $index = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @(
            "exec", "-T", "api", "python", "scripts/p4_entrypoint.py", "python",
            "scripts/rebuild_rag_indexes.py"
        )) -FailureMessage "RAG rebuild failed closed"
        $joined = ($index -join "`n")
        if ($joined -notmatch '"index_ready": true' -or $joined -notmatch '"chunk_count":') {
            throw "RAG index status is INDEX_BACKFILL_REQUIRED"
        }
        $joined
    }
    Invoke-Step "SQLBot readonly roles and Source Bindings" {
        $readonly = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @(
            "run", "--rm", "--no-deps", "runtime-bootstrap", "python",
            "scripts/p4_entrypoint.py", "python", "scripts/provision_platform_readonly_runtime.py"
        )) -FailureMessage "SQLBot readonly role provisioning failed"
        $bindings = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @(
            "exec", "-T", "api", "python", "scripts/p4_entrypoint.py", "python",
            "scripts/activate_sqlbot41c2_source_bindings.py"
        )) -FailureMessage "SQLBot Source Binding activation failed"
        (($readonly + $bindings) -join "`n")
    }
    Invoke-Step "Memory scheduler and Integration runtime" {
        $runtime = Invoke-CheckedNative -FilePath "docker" -Arguments ($composeArgs + @("exec", "-T", "api", "python", "scripts/p4_entrypoint.py", "python", "scripts/verify_integration41_runtime.py", "--timeout-seconds", "45", "--expected-revision", $expectedMigration, "--output", "/app/data/preproduction-evidence/integration41-runtime.json")) -FailureMessage "Integrated runtime verification failed"
        $joined = ($runtime -join "`n")
        if ($joined -notmatch '"status": "PASS"') {
            throw "Memory scheduler, RAG index or SQLBot shadow gate did not pass"
        }
        $joined
    }
    Invoke-Step "P6 frontend E2E" {
        $previousBaseUrl = $env:PLAYWRIGHT_BASE_URL
        $previousBrowsersPath = $env:PLAYWRIGHT_BROWSERS_PATH
        $previousOidcPassword = $env:P4_OIDC_PASSWORD
        $runtimePassword = $null
        $frontend = Join-Path $workspace "frontend"
        try {
            $env:PLAYWRIGHT_BASE_URL = $businessUrl
            $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $workspace ".cache/ms-playwright"
            $runtimePassword = & docker run --rm -v "${project}_p4_keycloak_runtime:/run/p4-keycloak:ro" --entrypoint python $apiImage -c "from pathlib import Path; print(Path('/run/p4-keycloak/keycloak_user_password').read_text().strip())" 2>$null
            if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($runtimePassword | Out-String))) {
                throw "P6 runtime-only OIDC acceptance credential is unavailable"
            }
            $env:P4_OIDC_PASSWORD = ($runtimePassword | Out-String).Trim()
            if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules/.bin/playwright.cmd"))) {
                Invoke-CheckedNative -FilePath "npm.cmd" -Arguments @("ci", "--prefix", "frontend", "--ignore-scripts") -FailureMessage "P6 frontend dependencies are unavailable" | Out-Null
            }
            Push-Location $frontend
            try {
                Invoke-CheckedNative -FilePath "npx.cmd" -Arguments @("playwright", "install", "chromium") -FailureMessage "P6 Playwright Chromium is unavailable" | Out-Null
                Invoke-CheckedNative -FilePath "npx.cmd" -Arguments @("playwright", "test", "e2e/p6-business-loop.spec.ts") -FailureMessage "P6 Playwright E2E failed"
            }
            finally {
                Pop-Location
            }
        }
        finally {
            $env:PLAYWRIGHT_BASE_URL = $previousBaseUrl
            $env:PLAYWRIGHT_BROWSERS_PATH = $previousBrowsersPath
            $env:P4_OIDC_PASSWORD = $previousOidcPassword
            $runtimePassword = $null
        }
    }
    Write-StartupReport -Status "PASS"
    Write-Host ""
    Write-Host "INTEGRATION-4.1-FULL PLATFORM STARTUP PASSED"
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
