param(
    [string]$SourceContainer = 'renewable-sqlbot-41b-runtime-v1-8-0',
    [string]$TargetContainer = 'renewable-sqlbot-41c-runtime-v1-10-0',
    [int]$HostPort = 18082
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
if (docker ps -a -q --filter "name=^/$TargetContainer$") {
    throw "Refusing to replace existing container: $TargetContainer"
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
    '-v', 'renewable-sqlbot41c-postgresql:/var/lib/postgresql/data',
    '-v', 'renewable-sqlbot41c-logs:/opt/sqlbot/app/logs',
    '-v', 'renewable-sqlbot41c-excel:/opt/sqlbot/data/excel',
    '-v', 'renewable-sqlbot41c-file:/opt/sqlbot/data/file',
    '-v', 'renewable-sqlbot41c-images:/opt/sqlbot/data/images',
    '--entrypoint', '/bin/sh',
    'registry.cn-qingdao.aliyuncs.com/dataease/sqlbot:v1.10.0',
    '/usr/local/bin/sqlbot-local-acceptance-start.sh'
)
docker @arguments | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SQLBot v1.10 acceptance container creation failed' }
docker start $TargetContainer | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SQLBot v1.10 acceptance container start failed' }
Write-Output '{"status":"STARTED","upstream":"v1.10.0","secret_values_exposed":false}'
