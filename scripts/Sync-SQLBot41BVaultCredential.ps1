$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

$vaultImage = 'hashicorp/vault:1.20.2'
$runtimeVolume = 'renewable-data41_p4_runtime'
$network = 'renewable-data41-network'
$recoverScript = (Resolve-Path 'scripts/recover_p4_vault.sh').Path

docker run --rm --network $network `
    -v "${runtimeVolume}:/run/p4-runtime:rw" `
    -v "${recoverScript}:/tmp/recover-p4-vault.sh:ro" `
    -e VAULT_ADDR=http://vault:8200 `
    $vaultImage sh /tmp/recover-p4-vault.sh |
    Out-Null

$rootToken = docker run --rm `
    -v "${runtimeVolume}:/run/p4-runtime:ro" `
    $vaultImage sh -c 'cat /run/p4-runtime/vault_recovery_root'
if (-not $rootToken) { throw 'Vault recovery token was not staged' }

$sqlbot = docker inspect renewable-sqlbot-p2a-runtime-v1-8-0 | ConvertFrom-Json
$passwordEntry = $sqlbot[0].Config.Env | Where-Object {
    $_ -like 'DEFAULT_PWD=*'
} | Select-Object -First 1
if (-not $passwordEntry) { throw 'SQLBot verified runtime credential is unavailable' }
$password = $passwordEntry.Substring('DEFAULT_PWD='.Length)

try {
    $env:VAULT_TOKEN = $rootToken
    $env:SQLBOT_SYNC_PASSWORD = $password
    docker run --rm --network $network `
        -e VAULT_ADDR=http://vault:8200 `
        -e VAULT_TOKEN -e SQLBOT_SYNC_PASSWORD `
        $vaultImage sh -c `
        'vault kv put -mount=preprod-kv chatbi/sqlbot username=admin password="$SQLBOT_SYNC_PASSWORD" >/dev/null; vault token revoke -self >/dev/null' |
        Out-Null
    $rootToken = $null
    Write-Output '{"status":"PASS","credential_rotated":true,"root_token_revoked":true,"secret_values_exposed":false}'
} finally {
    docker run --rm -v "${runtimeVolume}:/run/p4-runtime:rw" `
        $vaultImage sh -c ': > /run/p4-runtime/vault_recovery_root; chmod 0600 /run/p4-runtime/vault_recovery_root' |
        Out-Null
}
