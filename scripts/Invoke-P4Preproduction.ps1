[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "status", "migrate", "acceptance", "oidc-acceptance", "sqlbot-gate", "secret-rotation", "soak", "migration-check", "rollback")]
    [string]$Action = "status",
    [int]$SoakSeconds = 1800,
    [int]$Concurrency = 6,
    [switch]$ConfirmRollback
)

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$compose = Join-Path $workspace "deploy/preproduction/compose.yaml"
$project = "renewable-p4-rc"
$evidence = "/app/data/preproduction-evidence"

Push-Location $workspace
try {
    switch ($Action) {
        "start" { docker compose -p $project -f $compose up -d --build }
        "stop" { docker compose -p $project -f $compose stop }
        "status" { docker compose -p $project -f $compose ps -a }
        "migrate" { docker compose -p $project -f $compose run --rm migrate }
        "acceptance" {
            & (Join-Path $PSScriptRoot "Run-P4OidcAcceptance.ps1") -ComposeProject $project
            if ($LASTEXITCODE -ne 0) { throw "P4 OIDC acceptance failed" }
            docker compose -p $project -f $compose exec -T api python scripts/p4_entrypoint.py python scripts/run_p4_secret_rotation_acceptance.py --output "$evidence/p4_secret_rotation.json"
            if ($LASTEXITCODE -ne 0) { throw "P4 secret rotation acceptance failed" }
            docker compose -p $project -f $compose exec -T api python scripts/p4_entrypoint.py python scripts/run_p4_sqlbot_external_gate.py --output "$evidence/p4_sqlbot_external_gate.json"
            if ($LASTEXITCODE -notin 0, 2) { throw "P4 SQLBot gate failed" }
            docker compose -p $project -f $compose exec -T api python scripts/p4_entrypoint.py python scripts/run_p4_capacity_soak.py --duration-seconds $SoakSeconds --concurrency $Concurrency --output "$evidence/p4_capacity_soak.json"
        }
        "oidc-acceptance" { & (Join-Path $PSScriptRoot "Run-P4OidcAcceptance.ps1") -ComposeProject $project }
        "sqlbot-gate" {
            docker compose -p $project -f $compose exec -T api python scripts/p4_entrypoint.py python scripts/run_p4_sqlbot_external_gate.py --output "$evidence/p4_sqlbot_external_gate.json"
        }
        "secret-rotation" {
            docker compose -p $project -f $compose exec -T api python scripts/p4_entrypoint.py python scripts/run_p4_secret_rotation_acceptance.py --output "$evidence/p4_secret_rotation.json"
        }
        "soak" {
            docker compose -p $project -f $compose exec -T api python scripts/p4_entrypoint.py python scripts/run_p4_capacity_soak.py --duration-seconds $SoakSeconds --concurrency $Concurrency --output "$evidence/p4_capacity_soak.json"
        }
        "migration-check" {
            docker compose -p $project -f $compose exec -T api python scripts/p4_entrypoint.py python scripts/run_p3_migration_acceptance.py --database p4_preproduction_migration_verify
        }
        "rollback" {
            if (-not $ConfirmRollback) {
                throw "Rollback is fail-closed; repeat with -ConfirmRollback after reviewing the target p3_0001"
            }
            python (Join-Path $PSScriptRoot "run_p4_backup_restore.py")
            if ($LASTEXITCODE -ne 0) { throw "Verified pre-rollback backup failed" }
            docker compose -p $project -f $compose stop proxy web api backup
            if ($LASTEXITCODE -ne 0) { throw "Failed to stop P4 application services" }
            docker compose -p $project -f $compose run --rm migrate python scripts/p4_entrypoint.py alembic downgrade p3_0001
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "P4 action failed: $Action" }
}
finally { Pop-Location }
