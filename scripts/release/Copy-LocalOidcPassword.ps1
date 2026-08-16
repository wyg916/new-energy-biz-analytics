[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$project = "renewable-integration41-full"
$apiImage = "renewable-integration41-full-api:4.1.0-integration-full.1"
$credentialVolume = "${project}_p4_keycloak_runtime"
$credentialPath = "/run/p4-keycloak/keycloak_user_password"
$runtimePassword = $null
$clipboardValue = $null

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is unavailable. Start Docker Desktop and retry."
    }
    if (-not (Get-Command Set-Clipboard -ErrorAction SilentlyContinue)) {
        throw "Windows clipboard support is unavailable in this PowerShell session."
    }

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $runtimePassword = (& docker run --rm `
            --volume "${credentialVolume}:/run/p4-keycloak:ro" `
            --entrypoint python `
            $apiImage `
            -c "from pathlib import Path; print(Path('$credentialPath').read_text().strip())" `
            2>$null | Out-String).Trim()
        $dockerExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($dockerExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($runtimePassword)) {
        throw "The local OIDC credential is unavailable. Run the project launcher successfully, then retry."
    }

    Set-Clipboard -Value $runtimePassword
    $clipboardValue = Get-Clipboard -Raw
    if ($null -eq $clipboardValue) {
        throw "The clipboard returned no value."
    }
    $clipboardValue = $clipboardValue.TrimEnd([char[]]"`r`n")
    if ($clipboardValue -cne $runtimePassword) {
        throw "The clipboard copy could not be verified."
    }

    Write-Host "[PASS] Local OIDC login credential is ready."
    Write-Host "Username: p4.analyst"
    Write-Host "Password: copied to the Windows clipboard; paste it with Ctrl+V."
    Write-Host "Security: overwrite or clear the clipboard after login."
}
finally {
    $runtimePassword = $null
    $clipboardValue = $null
}
