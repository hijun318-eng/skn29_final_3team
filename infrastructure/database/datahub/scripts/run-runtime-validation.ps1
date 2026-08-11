[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$CheckpointPath
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$runtimePath = Join-Path $root 'src/data/datahub_runtime_evidence.i5.v1.json'
$bindingPath = Join-Path $root 'src/data/asset_binding_health.i5.v1.json'
$contractPath = Join-Path $root 'src/data/serving_analytics_contract.i4.v1.json'

$runtime = Get-Content -Raw -LiteralPath $runtimePath | ConvertFrom-Json
$bindings = Get-Content -Raw -LiteralPath $bindingPath | ConvertFrom-Json
$contract = Get-Content -Raw -LiteralPath $contractPath | ConvertFrom-Json

if (-not $DryRun) {
    if (-not $CheckpointPath -or -not (Test-Path -LiteralPath $CheckpointPath)) {
        throw 'R1_RUNTIME_HEALTHY checkpoint is required before live validation.'
    }
    $checkpoint = Get-Content -Raw -LiteralPath $CheckpointPath | ConvertFrom-Json
    if ($checkpoint.status -ne 'R1_RUNTIME_HEALTHY') {
        throw 'R1 runtime checkpoint is not healthy.'
    }
    throw 'Live ingestion is intentionally disabled in this offline validator revision.'
}

if ($runtime.status -ne 'BLOCKED' -or $runtime.runtime_execution -notin @('NOT_RUN', 'PARTIAL')) {
    throw 'Runtime evidence must remain truthfully BLOCKED with NOT_RUN or PARTIAL execution.'
}
if ($bindings.status -ne 'BLOCKED' -or $bindings.runtime_execution -ne 'NOT_RUN') {
    throw 'Asset Binding health must remain BLOCKED/NOT_RUN until live trace exists.'
}

$viewsByUrn = @{}
foreach ($view in $contract.views) { $viewsByUrn[$view.urn] = $view.fqn }
if ($viewsByUrn.Count -ne 8 -or $bindings.bindings.Count -ne 8) {
    throw 'The approved serving analytics asset set must contain exactly eight views.'
}
foreach ($binding in $bindings.bindings) {
    if ($viewsByUrn[$binding.urn] -ne $binding.fqn -or
        $binding.status -ne 'PENDING_RUNTIME_VERIFICATION' -or
        $null -ne $binding.verified_at) {
        throw "Asset Binding is not an unverified exact URN/FQN pair: $($binding.binding_id)"
    }
}

foreach ($step in $runtime.ingestion_plan) {
    $recipePath = Join-Path $root $step.recipe
    if (-not (Test-Path -LiteralPath $recipePath)) { throw "Recipe not found: $($step.recipe)" }
    $hash = (Get-FileHash -LiteralPath $recipePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $step.recipe_sha256) {
        throw "Recipe evidence drifted: $($step.recipe)"
    }
    if ($step.status -eq 'NOT_RUN') {
        if ($null -ne $step.exit_code -or $null -ne $step.run_id) {
            throw "Unexecuted recipe contains runtime evidence: $($step.recipe)"
        }
        continue
    }
    if ($step.status -notin @('PASS', 'FAIL') -or
        $null -eq $step.exit_code -or
        -not $step.run_id -or
        -not $step.started_at -or
        -not $step.finished_at) {
        throw "Executed recipe evidence is incomplete: $($step.recipe)"
    }
    if (($step.status -eq 'PASS' -and $step.exit_code -ne 0) -or
        ($step.status -eq 'FAIL' -and $step.exit_code -eq 0)) {
        throw "Recipe status and exit code disagree: $($step.recipe)"
    }
}

$rawEvidence = (Get-Content -Raw -LiteralPath $runtimePath) + (Get-Content -Raw -LiteralPath $bindingPath)
if ($rawEvidence -match '(?i)"[^"\r\n]*(password|secret|token|credential)[^"\r\n]*"\s*:') {
    throw 'Evidence contains a forbidden secret-bearing field.'
}

[ordered]@{
    status = 'DRY_RUN_PASS'
    runtime_status = $runtime.status
    runtime_execution = $runtime.runtime_execution
    recipe_count = $runtime.ingestion_plan.Count
    asset_binding_count = $bindings.bindings.Count
    next_checkpoint = $runtime.blocker.required_checkpoint
} | ConvertTo-Json -Compress
