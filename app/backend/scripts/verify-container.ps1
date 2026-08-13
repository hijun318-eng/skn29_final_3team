param(
    [switch]$RemoveAfterVerification
)

$ErrorActionPreference = 'Stop'

$backendPath = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Resolve-Path (Join-Path $backendPath '..\..')
$composeFile = Join-Path $repositoryRoot 'compose.yml'
$environmentFile = Join-Path $repositoryRoot 'infrastructure\database\.env'
$containerName = 'answervice-backend'
$composeArguments = @(
    'compose',
    '--env-file', $environmentFile,
    '-f', $composeFile,
    '--profile', 'full'
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
            $healthResponse = Invoke-RestMethod -Uri 'http://127.0.0.1:28000/health'
            $readinessResponse = Invoke-RestMethod -Uri 'http://127.0.0.1:28000/readiness'
            if ($healthResponse.data.status -ne 'healthy') {
                throw 'Backend /health response is not healthy.'
            }
            if (
                $readinessResponse.data.status -ne 'ready' -or
                $readinessResponse.data.dependencies.app_postgres -ne 'ready' -or
                $readinessResponse.data.dependencies.migration -ne 'ready' -or
                $readinessResponse.data.dependencies.approved_templates -ne 'ready' -or
                $readinessResponse.data.dependencies.trino -ne 'ready' -or
                $readinessResponse.data.dependencies.datahub -ne 'ready' -or
                $readinessResponse.data.dependencies.model -ne 'ready'
            ) {
                throw 'Backend /readiness did not confirm all product dependencies.'
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
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            docker @composeArguments stop backend 2>&1 | Out-Null
            $stopExitCode = $LASTEXITCODE
            docker @composeArguments rm --force backend 2>&1 | Out-Null
            $removeExitCode = $LASTEXITCODE
            $remainingContainers = @(
                docker ps -a --filter "name=^/$containerName$" --format '{{.Names}}' 2>&1
            )
            $inspectionExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        if ($stopExitCode -ne 0) {
            throw 'Backend Compose service stop failed.'
        }
        if ($removeExitCode -ne 0) {
            throw 'Backend Compose service removal failed.'
        }
        if ($inspectionExitCode -ne 0) {
            throw 'Backend container removal verification failed.'
        }
        if ($remainingContainers -contains $containerName) {
            throw 'Backend container remains after cleanup.'
        }
        Write-Output 'BACKEND_CONTAINER_REMOVED'
    }
}
