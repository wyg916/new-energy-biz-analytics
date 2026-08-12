param(
    [string]$SourceContainer = 'renewable-sqlbot-41b-runtime-v1-8-0',
    [string]$TargetContainer = 'renewable-sqlbot-41c-runtime-v1-10-0',
    [int]$HostPort = 18082,
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$VolumePrefix = 'renewable-sqlbot41c',
    [string]$ProviderCredentialVolume = '',
    [int]$HealthTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

function Connect-PlatformNetwork {
    $target = (docker inspect $TargetContainer | ConvertFrom-Json)[0]
    $networkNames = @($target.NetworkSettings.Networks.psobject.Properties.Name)
    if ($networkNames -notcontains $PlatformNetwork) {
        docker network connect $PlatformNetwork $TargetContainer | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to connect SQLBot Runtime to $PlatformNetwork"
        }
    }
}

function Wait-SQLBotRuntime {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    do {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & curl.exe --silent --show-error --fail `
                "http://127.0.0.1:${HostPort}/" 1>$null 2>$null
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($exitCode -eq 0) { return }
        Start-Sleep -Seconds 2
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "SQLBot Runtime did not become healthy within $HealthTimeoutSeconds seconds"
}

$existingTarget = docker ps -a -q --filter "name=^/$TargetContainer$"
if ($existingTarget) {
    $running = docker inspect $TargetContainer --format '{{.State.Running}}'
    if ($running -ne 'true') {
        docker start $TargetContainer | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Existing SQLBot v1.10 runtime failed to start' }
    }
    Connect-PlatformNetwork
    Wait-SQLBotRuntime
    Write-Output '{"status":"READY","action":"REUSED","upstream":"v1.10.0","secret_values_exposed":false}'
    return
}
$source = (docker inspect $SourceContainer | ConvertFrom-Json)[0]
$allowedEnvironment = @(
    'POSTGRES_SERVER', 'POSTGRES_PORT', 'POSTGRES_DB', 'POSTGRES_USER',
    'POSTGRES_PASSWORD', 'PROJECT_NAME', 'DEFAULT_PWD', 'SECRET_KEY',
    'BACKEND_CORS_ORIGINS', 'LOG_LEVEL', 'SQL_DEBUG', 'CACHE_TYPE',
    'ACCESS_TOKEN_EXPIRE_MINUTES', 'CONTEXT_PATH',
    'SQLBOT_LOCAL_DB_READY_ATTEMPTS', 'SQLBOT_LOCAL_DB_READY_INTERVAL_SECONDS'
)
$arguments = @(
    'create', '--name', $TargetContainer,
    '--restart', 'unless-stopped', '--privileged',
    '--network', 'renewable-sqlbot-proxy',
    '-p', "127.0.0.1:${HostPort}:8000"
)
foreach ($name in $allowedEnvironment) {
    $entry = $source.Config.Env | Where-Object { $_ -like "${name}=*" } | Select-Object -First 1
    if ($entry) { $arguments += @('-e', $entry) }
}
$arguments += @(
    '-e', 'SQLBOT_UPSTREAM_VERSION=v1.10.0',
    '-v', "${root}\deploy\sqlbot\start-local-acceptance.sh:/usr/local/bin/sqlbot-local-acceptance-start.sh:ro",
    '-v', "${root}\deploy\sqlbot\sqlbot41_runtime.py:/opt/sqlbot/app/sqlbot41_runtime.py:ro",
    '-v', "${VolumePrefix}-postgresql:/var/lib/postgresql/data",
    '-v', "${VolumePrefix}-logs:/opt/sqlbot/app/logs",
    '-v', "${VolumePrefix}-excel:/opt/sqlbot/data/excel",
    '-v', "${VolumePrefix}-file:/opt/sqlbot/data/file",
    '-v', "${VolumePrefix}-images:/opt/sqlbot/data/images"
)
if ($ProviderCredentialVolume) {
    $arguments += @('-v', "${ProviderCredentialVolume}:/run/provider-credentials:ro")
}
$arguments += @(
    '--entrypoint', '/bin/sh',
    'registry.cn-qingdao.aliyuncs.com/dataease/sqlbot:v1.10.0',
    '/usr/local/bin/sqlbot-local-acceptance-start.sh'
)
docker @arguments | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SQLBot v1.10 acceptance container creation failed' }
docker start $TargetContainer | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SQLBot v1.10 acceptance container start failed' }
Connect-PlatformNetwork
Wait-SQLBotRuntime
Write-Output '{"status":"READY","action":"CREATED","upstream":"v1.10.0","secret_values_exposed":false}'
