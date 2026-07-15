[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw "Run this script inside the Git repository."
}

$source = Join-Path $repoRoot "docs\engineering\CODEX_GLOBAL_AGENTS.md"
if (-not (Test-Path -LiteralPath $source)) {
    throw "Canonical global AGENTS file not found: $source"
}

$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
$target = Join-Path $codexHome "AGENTS.md"
$override = Join-Path $codexHome "AGENTS.override.md"

if ($CheckOnly) {
    if (-not (Test-Path -LiteralPath $target)) {
        Write-Output "Global AGENTS: missing"
        exit 1
    }
    $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
    $targetHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
    Write-Output "Canonical SHA256: $sourceHash"
    Write-Output "Installed SHA256: $targetHash"
    if ($sourceHash -ne $targetHash) {
        Write-Warning "Global AGENTS differs from the canonical team file."
        exit 1
    }
    if (Test-Path -LiteralPath $override) {
        Write-Warning "AGENTS.override.md exists and takes precedence over AGENTS.md."
    }
    Write-Output "Global AGENTS is synchronized."
    exit 0
}

if ((Test-Path -LiteralPath $target) -and -not $Force) {
    throw "Global AGENTS already exists. Run with -Force only after reviewing it: $target"
}

New-Item -ItemType Directory -Path $codexHome -Force | Out-Null
if (Test-Path -LiteralPath $target) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$target.backup-$stamp"
    Copy-Item -LiteralPath $target -Destination $backup
    Write-Output "Backed up existing global AGENTS to: $backup"
}
Copy-Item -LiteralPath $source -Destination $target -Force

Write-Output "Installed canonical global AGENTS: $target"
if (Test-Path -LiteralPath $override) {
    Write-Warning "AGENTS.override.md exists and still takes precedence."
}
