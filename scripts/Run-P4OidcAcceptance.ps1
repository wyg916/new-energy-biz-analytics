[CmdletBinding()]
param(
    [string]$ComposeProject = "renewable-p4-rc",
    [string]$BaseUrl = "https://p4.localhost:8444"
)

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $workspace "frontend"
$volume = "${ComposeProject}_p4_keycloak_runtime"
$runtimePassword = docker run --rm -v "${volume}:/run/p4-keycloak:ro" alpine:3.21 sh -ec "cat /run/p4-keycloak/keycloak_user_password"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($runtimePassword)) {
    throw "P4 runtime-only OIDC acceptance credential is unavailable"
}
try {
    $env:P4_OIDC_PASSWORD = $runtimePassword.Trim()
    $env:PLAYWRIGHT_BASE_URL = $BaseUrl
    Push-Location $frontend
    try {
        & npx.cmd playwright test e2e/p4-preproduction-oidc.spec.ts
        if ($LASTEXITCODE -ne 0) { throw "P4 OIDC Playwright acceptance failed" }
    }
    finally { Pop-Location }
}
finally {
    Remove-Item Env:P4_OIDC_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:PLAYWRIGHT_BASE_URL -ErrorAction SilentlyContinue
    $runtimePassword = $null
}
Write-Output '{"status":"PASS","flow":"authorization_code_pkce","secret_values_printed":false}'
