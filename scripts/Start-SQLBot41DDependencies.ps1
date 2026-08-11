param(
    [string]$PlatformNetwork = 'renewable-data41-network',
    [string]$RuntimeVolume = 'renewable-data41_p4_runtime',
    [string]$RedisDataVolume = 'renewable-data41_p4_redis',
    [string]$RedisContainer = 'renewable-data41-redis-1',
    [string]$RedisImage = 'redis:7.4.10-alpine@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2',
    [string]$SQLBotContainer = 'renewable-sqlbot-41c-runtime-v1-10-0',
    [int]$SQLBotHostPort = 18082,
    [string]$SQLBotVolumePrefix = 'renewable-sqlbot41c'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

function Require-DockerObject {
    param([string[]]$Arguments, [string]$Message)
    $null = docker @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

Require-DockerObject -Arguments @('network', 'inspect', $PlatformNetwork) `
    -Message "Required platform network is unavailable: $PlatformNetwork"
Require-DockerObject -Arguments @('volume', 'inspect', $RuntimeVolume) `
    -Message "Required governed runtime volume is unavailable: $RuntimeVolume"
Require-DockerObject -Arguments @('volume', 'inspect', $RedisDataVolume) `
    -Message "Required Redis data volume is unavailable: $RedisDataVolume"

$redisAction = 'REUSED'
$existingRedis = docker ps -a -q --filter "name=^/$RedisContainer$"
if (-not $existingRedis) {
    docker create --name $RedisContainer `
        --restart unless-stopped `
        --network $PlatformNetwork `
        --network-alias redis `
        -v "${RedisDataVolume}:/data" `
        -v "${RuntimeVolume}:/run/p4-runtime:ro" `
        $RedisImage redis-server /run/p4-runtime/redis.conf | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'SQLBot 4.1D Redis creation failed' }
    $redisAction = 'CREATED'
}
else {
    $redisInspect = (docker inspect $RedisContainer | ConvertFrom-Json)[0]
    $redisNetworks = @($redisInspect.NetworkSettings.Networks.psobject.Properties.Name)
    if ($redisNetworks -notcontains $PlatformNetwork) {
        docker network connect --alias redis $PlatformNetwork $RedisContainer | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to connect Redis to the platform network' }
    }
}

$redisRunning = docker inspect $RedisContainer --format '{{.State.Running}}'
if ($redisRunning -ne 'true') {
    docker start $RedisContainer | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'SQLBot 4.1D Redis failed to start' }
}
$redisPing = docker exec $RedisContainer sh -c `
    'export REDISCLI_AUTH=$(cat /run/p4-runtime/redis_password); exec redis-cli ping'
if ($LASTEXITCODE -ne 0 -or ($redisPing | Out-String).Trim() -ne 'PONG') {
    throw 'SQLBot 4.1D Redis authentication health check failed'
}

$sqlbotResult = & (Join-Path $PSScriptRoot 'Start-SQLBot41CV110Acceptance.ps1') `
    -TargetContainer $SQLBotContainer `
    -HostPort $SQLBotHostPort `
    -PlatformNetwork $PlatformNetwork `
    -VolumePrefix $SQLBotVolumePrefix
if ($LASTEXITCODE -ne 0) { throw 'SQLBot Runtime startup failed' }

[ordered]@{
    status = 'PASS'
    redis = [ordered]@{
        container = $RedisContainer
        action = $redisAction
        authenticated_health = 'PONG'
    }
    sqlbot = (($sqlbotResult | Out-String).Trim() | ConvertFrom-Json)
    platform_network = $PlatformNetwork
    secret_values_exposed = $false
} | ConvertTo-Json -Depth 5
