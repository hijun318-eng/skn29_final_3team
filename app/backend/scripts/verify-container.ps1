# 책임: 실제 Compose backend의 transport health와 모든 product dependency readiness를
# 함께 검증한다. cached 응답이나 일부 dependency 성공으로 READY를 만들지 않는다.
param(
    [switch]$RemoveAfterVerification,
    [switch]$AllowRepositoryLocalDevelopment,
    [string]$BackendBaseUrl = $env:ANSWERVICE_BACKEND_BASE_URL,
    [string]$EnvFilePath,
    [string]$SearchRollbackReceiptPath,
    [ValidateRange(1, 1800)]
    [int]$MaxSearchTransitionSeconds = 180
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
$retrievalGateGold = '/workspace/evals/metric_retrieval_gold/answervice_ko_retrieval.v2.json'
if (-not $BackendBaseUrl) { $BackendBaseUrl = 'http://127.0.0.1:28000' }
$BackendBaseUrl = $BackendBaseUrl.TrimEnd('/')
$composeArguments = @('compose') + $composeEnvArguments + @(
    '-f', $composeFile,
    '--profile', 'full'
)
$originalSearchMode = $env:DATAHUB_SEARCH_MODE
$resolvedRollbackReceiptPath = $null
$rehearsalStartedAt = $null
$verificationModes = @(
    [pscustomobject]@{ Stage = 'current'; Mode = '' }
)
if ($SearchRollbackReceiptPath) {
    if ($RemoveAfterVerification) {
        throw 'Search rollback rehearsal must leave the restored candidate running.'
    }
    $receiptCandidate = if ([IO.Path]::IsPathRooted($SearchRollbackReceiptPath)) {
        [IO.Path]::GetFullPath($SearchRollbackReceiptPath)
    }
    else {
        [IO.Path]::GetFullPath((Join-Path $repositoryRoot $SearchRollbackReceiptPath))
    }
    $repositoryPrefix = $repositoryRoot.TrimEnd(
        [IO.Path]::DirectorySeparatorChar
    ) + [IO.Path]::DirectorySeparatorChar
    $receiptParentCandidate = Split-Path -Parent $receiptCandidate
    if (-not (Test-Path -LiteralPath $receiptParentCandidate -PathType Container)) {
        throw 'Search rollback receipt parent directory must already exist.'
    }
    $resolvedReceiptParent = (Resolve-Path -LiteralPath $receiptParentCandidate).Path
    $receiptCandidate = Join-Path $resolvedReceiptParent (
        Split-Path -Leaf $receiptCandidate
    )
    if (
        -not $receiptCandidate.StartsWith(
            $repositoryPrefix,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetExtension($receiptCandidate) -cne '.json' -or
        (Test-Path -LiteralPath $receiptCandidate)
    ) {
        throw 'Search rollback receipt must be a new JSON file inside the repository.'
    }
    & git -C $repositoryRoot check-ignore -q -- $receiptCandidate
    if ($LASTEXITCODE -ne 0) {
        throw 'Search rollback receipt path must be covered by .gitignore.'
    }
    $resolvedRollbackReceiptPath = $receiptCandidate
    $rehearsalStartedAt = [DateTimeOffset]::UtcNow
    $verificationModes = @(
        [pscustomobject]@{ Stage = 'candidate_baseline'; Mode = 'datahub_lexical' }
        [pscustomobject]@{ Stage = 'lexical_rollback'; Mode = 'lexical' }
        [pscustomobject]@{ Stage = 'candidate_restore'; Mode = 'datahub_lexical' }
    )
}
$transitionReceipts = @()

try {
    foreach ($verificationMode in $verificationModes) {
        if ($verificationMode.Mode) {
            $env:DATAHUB_SEARCH_MODE = $verificationMode.Mode
        }
        $stepStartedAt = [DateTimeOffset]::UtcNow
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
        $healthTimeoutSeconds = if ($resolvedRollbackReceiptPath) {
            [math]::Min(180, $MaxSearchTransitionSeconds)
        }
        else {
            180
        }
        $deadline = (Get-Date).AddSeconds($healthTimeoutSeconds)
        $verified = $false
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
                $actualSearchModeOutput = @(
                    docker exec $containerName printenv DATAHUB_SEARCH_MODE
                )
                $actualSearchModeExitCode = $LASTEXITCODE
                $actualSearchMode = ($actualSearchModeOutput -join '').Trim()
                if (
                    $actualSearchModeExitCode -ne 0 -or
                    @('lexical', 'lexical_shadow', 'datahub_lexical', 'hybrid') `
                        -notcontains $actualSearchMode -or
                    ($verificationMode.Mode -and
                        $actualSearchMode -cne $verificationMode.Mode)
                ) {
                    throw 'Backend search mode does not match the requested deployment mode.'
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
                    $retrievalGate.contract_version -ne 'answervice.metric_retrieval_phase2a.v2' -or
                    $retrievalGate.gate -ne '2A' -or
                    $retrievalGate.status -ne 'PASSED' -or
                    $retrievalGate.decision -ne 'PROMOTE'
                ) {
                    $failedChecks = @(
                        $retrievalGate.checks.PSObject.Properties |
                            Where-Object { -not [bool]$_.Value } |
                            ForEach-Object { $_.Name }
                    )
                    throw "Backend Phase 2A retrieval Gate failed: $($failedChecks -join ', ')."
                }
                $stepEndedAt = [DateTimeOffset]::UtcNow
                $recoverySeconds = [math]::Round(
                    ($stepEndedAt - $stepStartedAt).TotalSeconds,
                    3
                )
                if (
                    $resolvedRollbackReceiptPath -and
                    $recoverySeconds -gt $MaxSearchTransitionSeconds
                ) {
                    throw 'Backend search transition exceeded the predeclared bound.'
                }
                $transitionReceipts += [ordered]@{
                    stage = $verificationMode.Stage
                    search_mode = $actualSearchMode
                    started_at_utc = $stepStartedAt.ToString('O')
                    ended_at_utc = $stepEndedAt.ToString('O')
                    recovery_seconds = $recoverySeconds
                    readiness_dependency_count = $readinessDependencies.Count
                    readiness_dependencies = @(
                        $readinessDependencies.Name | Sort-Object
                    )
                    gate_decision = [string]$retrievalGate.decision
                    gate_contract_version = [string]$retrievalGate.contract_version
                    context_release = [string]$retrievalGate.context_release
                    catalog_checksum = [string]$retrievalGate.catalog_checksum
                    canonical_checksum = [string]$retrievalGate.canonical_checksum
                    gold_dataset_id = [string]$retrievalGate.gold_manifest.dataset_id
                    gold_content_sha256 = [string]$retrievalGate.gold_manifest.content_sha256
                    search_reliability = $retrievalGate.search_reliability
                }
                Write-Output "BACKEND_SEARCH_MODE_READY=$actualSearchMode"
                Write-Output 'BACKEND_CONTAINER_READY'
                Write-Output 'BACKEND_DATABASE_READY'
                Write-Output 'BACKEND_IMAGE_PROVENANCE_READY'
                Write-Output 'BACKEND_METRIC_RETRIEVAL_READY'
                $verified = $true
                break
            }
            if ($health -eq 'unhealthy') {
                throw 'Backend container health check failed.'
            }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $deadline)

        if (-not $verified) {
            throw "Backend container did not become healthy within $healthTimeoutSeconds seconds."
        }
    }

    if ($resolvedRollbackReceiptPath) {
        $releaseIdentities = @(
            $transitionReceipts | ForEach-Object {
                "$($_.context_release)|$($_.catalog_checksum)|$($_.canonical_checksum)"
            } | Select-Object -Unique
        )
        $goldIdentities = @(
            $transitionReceipts | ForEach-Object {
                "$($_.gold_dataset_id)|$($_.gold_content_sha256)"
            } | Select-Object -Unique
        )
        if (
            $transitionReceipts.Count -ne 3 -or
            $releaseIdentities.Count -ne 1 -or
            $goldIdentities.Count -ne 1
        ) {
            throw 'Search rollback rehearsal crossed a release or Gold identity.'
        }
        $receipt = [ordered]@{
            schema_version = 'answervice.search-rollback-receipt.v1'
            scope = 'P0-DATAHUB-SEARCH_PROCESS_MODE_ONLY'
            started_at_utc = $rehearsalStartedAt.ToString('O')
            ended_at_utc = [DateTimeOffset]::UtcNow.ToString('O')
            max_transition_seconds = $MaxSearchTransitionSeconds
            source_revision = $sourceProvenance.Revision
            source_dirty = $sourceProvenance.Dirty
            source_fingerprint = $sourceProvenance.Fingerprint
            transitions = $transitionReceipts
            status = 'PASS'
        }
        $temporaryReceiptPath = "$resolvedRollbackReceiptPath.tmp"
        if (Test-Path -LiteralPath $temporaryReceiptPath) {
            throw 'Search rollback temporary receipt already exists.'
        }
        [IO.File]::WriteAllText(
            $temporaryReceiptPath,
            (($receipt | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporaryReceiptPath `
            -Destination $resolvedRollbackReceiptPath
        Write-Output "BACKEND_SEARCH_ROLLBACK_VERIFIED=$resolvedRollbackReceiptPath"
    }
}
finally {
    if ($null -eq $originalSearchMode) {
        Remove-Item Env:DATAHUB_SEARCH_MODE -ErrorAction SilentlyContinue
    }
    else {
        $env:DATAHUB_SEARCH_MODE = $originalSearchMode
    }
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
