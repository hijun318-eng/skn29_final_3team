param(
    [switch]$RemoveAfterVerification
)

$ErrorActionPreference = 'Stop'

$backendPath = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Resolve-Path (Join-Path $backendPath '..\..')
$databaseCompose = Join-Path $repositoryRoot 'infrastructure\database\compose.yml'
$backendCompose = Join-Path $backendPath 'compose.fragment.yml'
$environmentFile = Join-Path $repositoryRoot 'infrastructure\database\.env'
$containerName = 'answervice-backend'
$composeArguments = @(
    'compose',
    '--env-file', $environmentFile,
    '-f', $databaseCompose,
    '-f', $backendCompose
)

try {
    if (-not (Test-Path -LiteralPath $environmentFile)) {
        throw 'infrastructure/database/.env is required for Compose validation.'
    }

    docker @composeArguments config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'Combined database and backend Compose validation failed.'
    }

    docker @composeArguments up --detach --build backend
    if ($LASTEXITCODE -ne 0) {
        throw 'Backend Compose service start failed.'
    }

    $deadline = (Get-Date).AddSeconds(40)
    do {
        $health = docker inspect --format '{{.State.Health.Status}}' $containerName
        if ($health -eq 'healthy') {
            $healthResponse = Invoke-RestMethod -Uri 'http://127.0.0.1:18000/health'
            $readinessResponse = Invoke-RestMethod -Uri 'http://127.0.0.1:18000/readiness'
            if ($healthResponse.data.status -ne 'healthy') {
                throw 'Backend /health response is not healthy.'
            }
            if (
                $readinessResponse.data.status -ne 'ready' -or
                $readinessResponse.data.dependencies.app_postgres -ne 'reachable'
            ) {
                throw 'Backend /readiness did not confirm app-postgres connectivity.'
            }
            Write-Output 'BACKEND_CONTAINER_READY'
            Write-Output 'BACKEND_DATABASE_READY'
            exit 0
        }
        if ($health -eq 'unhealthy') {
            throw 'Backend container health check failed.'
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    throw 'Backend container did not become healthy within 40 seconds.'
}
finally {
    if ($RemoveAfterVerification) {
        docker @composeArguments stop backend 2>$null | Out-Null
        docker @composeArguments rm --force backend 2>$null | Out-Null
    }
}
