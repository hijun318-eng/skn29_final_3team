[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$runtimePath = Join-Path $root 'src/data/datahub_runtime_evidence.i5.v1.json'
$bindingPath = Join-Path $root 'src/data/asset_binding_health.i5.v1.json'
$contractPath = Join-Path $root 'src/data/serving_analytics_contract.i4.v1.json'

$runtime = Get-Content -Raw -LiteralPath $runtimePath | ConvertFrom-Json
$bindings = Get-Content -Raw -LiteralPath $bindingPath | ConvertFrom-Json
$contract = Get-Content -Raw -LiteralPath $contractPath | ConvertFrom-Json

if ($runtime.status -ne 'PASS' -or $runtime.runtime_execution -ne 'PASS') {
    throw 'Runtime evidence must record a successful live validation.'
}
if ($bindings.status -ne 'HEALTHY' -or $bindings.runtime_execution -ne 'PASS') {
    throw 'Asset Binding health must record exact live verification.'
}

$viewsByUrn = @{}
foreach ($view in $contract.views) { $viewsByUrn[$view.urn] = $view.fqn }
if ($viewsByUrn.Count -ne 8 -or $bindings.bindings.Count -ne 8) {
    throw 'The approved serving analytics asset set must contain exactly eight views.'
}
foreach ($binding in $bindings.bindings) {
    if ($viewsByUrn[$binding.urn] -ne $binding.fqn -or
        $binding.status -ne 'VERIFIED' -or
        -not $binding.verified_at) {
        throw "Asset Binding is not a verified exact URN/FQN pair: $($binding.binding_id)"
    }
}

foreach ($step in $runtime.ingestion_plan) {
    $recipePath = Join-Path $root $step.recipe
    if (-not (Test-Path -LiteralPath $recipePath)) { throw "Recipe not found: $($step.recipe)" }
    $hash = (Get-FileHash -LiteralPath $recipePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $step.recipe_sha256 -or $step.status -ne 'PASS' -or $step.exit_code -ne 0) {
        throw "Recipe evidence drifted: $($step.recipe)"
    }
}
foreach ($observation in $runtime.observed.PSObject.Properties.Value) {
    if ($observation.status -ne 'PASS' -or $observation.canonical_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'Observed runtime evidence is incomplete.'
    }
}

$rawEvidence = (Get-Content -Raw -LiteralPath $runtimePath) + (Get-Content -Raw -LiteralPath $bindingPath)
if ($rawEvidence -match '(?i)"[^"\r\n]*(password|secret|token|credential)[^"\r\n]*"\s*:') {
    throw 'Evidence contains a forbidden secret-bearing field.'
}

[ordered]@{
    status = if ($DryRun) { 'DRY_RUN_PASS' } else { 'VERIFIED' }
    runtime_status = $runtime.status
    runtime_execution = $runtime.runtime_execution
    recipe_count = $runtime.ingestion_plan.Count
    asset_binding_count = $bindings.bindings.Count
    recorded_at = $runtime.recorded_at
} | ConvertTo-Json -Compress
