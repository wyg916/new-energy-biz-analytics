[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "status", "migrate", "oidc-acceptance", "soak")]
    [string]$Action = "status",
    [int]$SoakSeconds = 7200,
    [int]$Concurrency = 20
)

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$baseCompose = Join-Path $workspace "deploy/preproduction/compose.yaml"
$overrideCompose = Join-Path $workspace "deploy/production-acceptance/p5a.override.yaml"
$project = "renewable-p5a-remediation"
$evidence = "/app/data/preproduction-evidence"
$composeArgs = @("compose", "-p", $project, "-f", $baseCompose, "-f", $overrideCompose)
$previousComposeBake = $env:COMPOSE_BAKE
$env:COMPOSE_BAKE = "false"

function Invoke-DockerStep {
    param([string[]]$Arguments)
    docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed: docker $($Arguments -join ' ')"
    }
}

function Build-P5AImages {
    Invoke-DockerStep @(
        "build", "--progress=plain", "--provenance=false", "-f", "backend/Dockerfile",
        "-t", "renewable-p5a-api:5.0.0-p5a", $workspace
    )
    Invoke-DockerStep @("tag", "renewable-p5a-api:5.0.0-p5a", "renewable-p5a-migration:5.0.0-p5a")
    Invoke-DockerStep @("tag", "renewable-p5a-api:5.0.0-p5a", "renewable-p5a-alert-receiver:5.0.0-p5a")
    Invoke-DockerStep @(
        "build", "--progress=plain", "--provenance=false", "-f", "deploy/preproduction/postgres.Dockerfile",
        "-t", "renewable-p5a-postgres:16.14", $workspace
    )
    Invoke-DockerStep @("tag", "renewable-p5a-postgres:16.14", "renewable-p5a-backup:16.14")
    Invoke-DockerStep @(
        "build", "--progress=plain", "--provenance=false", "-f", "deploy/preproduction/keycloak.Dockerfile",
        "-t", "renewable-p5a-keycloak:26.7.0", $workspace
    )
    Invoke-DockerStep @(
        "build", "--progress=plain", "--provenance=false", "-f", "frontend/Dockerfile",
        "-t", "renewable-p5a-web:5.0.0-p5a", (Join-Path $workspace "frontend")
    )
}

Push-Location $workspace
try {
    switch ($Action) {
        "start" {
            Build-P5AImages
            docker @composeArgs up -d
        }
        "stop" { docker @composeArgs stop }
        "status" { docker @composeArgs ps -a }
        "migrate" { docker @composeArgs run --rm migrate }
        "oidc-acceptance" {
            & (Join-Path $PSScriptRoot "Run-P4OidcAcceptance.ps1") `
                -ComposeProject $project -BaseUrl "https://p5a.localhost:8445"
        }
        "soak" {
            docker @composeArgs exec -T api python scripts/p4_entrypoint.py `
                python scripts/run_p5_capacity_acceptance.py `
                --base-url "https://p5a.localhost:8445" `
                --duration-seconds $SoakSeconds --concurrency $Concurrency `
                --output "$evidence/p5a_capacity_soak.json"
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "P5A action failed: $Action" }
}
finally {
    if ($null -eq $previousComposeBake) {
        Remove-Item Env:COMPOSE_BAKE -ErrorAction SilentlyContinue
    }
    else {
        $env:COMPOSE_BAKE = $previousComposeBake
    }
    Pop-Location
}
