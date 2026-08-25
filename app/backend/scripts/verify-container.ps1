# 책임: 실제 Compose backend의 transport health와 모든 product dependency readiness를
# 함께 검증한다. cached 응답이나 일부 dependency 성공으로 READY를 만들지 않는다.
param(
    [switch]$RemoveAfterVerification,
    [switch]$AllowRepositoryLocalDevelopment,
    [string]$BackendBaseUrl = $env:ANSWERVICE_BACKEND_BASE_URL,
    [string]$EnvFilePath
)

$ErrorActionPreference = 'Stop'

$backendPath = Split-Path -Parent $PSScriptRoot
$repositoryRoot = (Resolve-Path (Join-Path $backendPath '..\..')).Path
$composeFile = Join-Path $repositoryRoot 'compose.yml'
. (Join-Path $repositoryRoot 'infrastructure\database\scripts\deployment-environment.ps1')
. (Join-Path $PSScriptRoot 'source-provenance.ps1')
Disable-ImplicitComposeEnvironment
$environmentFile = Resolve-ExplicitDeploymentEnvFile `
    -Path $EnvFilePath `
    -RepositoryRoot $repositoryRoot `
    -AllowRepositoryLocalDevelopment:$AllowRepositoryLocalDevelopment
$sourceProvenance = Set-AnswerviceSourceProvenanceEnvironment `
    -RepositoryRoot $repositoryRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $environmentFile)
$containerName = 'answervice-backend'
$retrievalGateRunner = '/workspace/evals/metric_retrieval_runner.py'
$retrievalGateGold = '/workspace/evals/metric_retrieval_gold/answervice_ko_retrieval.v1.json'
if (-not $BackendBaseUrl) { $BackendBaseUrl = 'http://127.0.0.1:28000' }
$BackendBaseUrl = $BackendBaseUrl.TrimEnd('/')
$composeArguments = @('compose') + $composeEnvArguments + @(
    '-f', $composeFile,
    '--profile', 'full'
)

try {
    docker @composeArguments config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw 'Combined database and backend Compose validation failed.'
    }

    docker @composeArguments up --detach --build backend
    if ($LASTEXITCODE -ne 0) {
        throw 'Backend Compose service start failed.'
    }

    # Container health is only a transport probe. Product readiness below must
    # independently prove every live dependency and cannot be replaced by a
    # cached fixture or previously successful response.
    $deadline = (Get-Date).AddSeconds(180)
    do {
        $health = docker inspect --format '{{.State.Health.Status}}' $containerName
        if ($health -eq 'healthy') {
            $healthResponse = Invoke-RestMethod -Uri "$BackendBaseUrl/health"
            $readinessResponse = Invoke-RestMethod -Uri "$BackendBaseUrl/readiness"
            if ($healthResponse.data.status -ne 'healthy') {
                throw 'Backend /health response is not healthy.'
            }
            $readinessDependencies = @(
                $readinessResponse.data.dependencies.PSObject.Properties
            )
            $notReadyDependencies = @(
                $readinessDependencies | Where-Object { $_.Value -ne 'ready' }
            )
            if (
                $readinessResponse.data.status -ne 'ready' -or
                $readinessDependencies.Count -eq 0 -or
                $notReadyDependencies.Count -gt 0
            ) {
                throw 'Backend /readiness did not confirm all product dependencies.'
            }
            $imageLabelsOutput = @(
                docker inspect --format '{{json .Config.Labels}}' $containerName
            )
            $imageLabelsExitCode = $LASTEXITCODE
            try {
                $imageLabels = ($imageLabelsOutput -join '') | ConvertFrom-Json
            }
            catch {
                throw "Backend image provenance labels are invalid (exit $imageLabelsExitCode)."
            }
            if (
                $imageLabelsExitCode -ne 0 -or
                $imageLabels.'org.opencontainers.image.revision' -ne $sourceProvenance.Revision -or
                $imageLabels.'io.answervice.source.dirty' -ne $sourceProvenance.Dirty -or
                $imageLabels.'io.answervice.source.fingerprint' -ne $sourceProvenance.Fingerprint
            ) {
                throw 'Backend image provenance labels do not match the verified source tree.'
            }
            $retrievalGateOutput = @(
                docker exec $containerName python $retrievalGateRunner `
                    --phase2a-gold-manifest $retrievalGateGold
            )
            $retrievalGateExitCode = $LASTEXITCODE
            try {
                $retrievalGate = (
                    $retrievalGateOutput -join [Environment]::NewLine
                ) | ConvertFrom-Json
            }
            catch {
                throw "Backend Phase 2A retrieval Gate returned invalid JSON (exit $retrievalGateExitCode)."
            }
            if (
                $retrievalGateExitCode -ne 0 -or
                $retrievalGate.contract_version -ne 'answervice.metric_retrieval_phase2a.v1' -or
                $retrievalGate.gate -ne '2A' -or
                $retrievalGate.status -ne 'PASSED'
            ) {
                $failedChecks = @(
                    $retrievalGate.checks.PSObject.Properties |
                        Where-Object { -not [bool]$_.Value } |
                        ForEach-Object { $_.Name }
                )
                throw "Backend Phase 2A retrieval Gate failed: $($failedChecks -join ', ')."
            }
            Write-Output 'BACKEND_CONTAINER_READY'
            Write-Output 'BACKEND_DATABASE_READY'
            Write-Output 'BACKEND_IMAGE_PROVENANCE_READY'
            Write-Output 'BACKEND_METRIC_RETRIEVAL_READY'
            exit 0
        }
        if ($health -eq 'unhealthy') {
            throw 'Backend container health check failed.'
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    throw 'Backend container did not become healthy within 180 seconds.'
}
finally {
    if ($RemoveAfterVerification) {
        # Cleanup targets the exact service and then verifies absence. Volumes
        # and unrelated containers are intentionally outside this operation.
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
