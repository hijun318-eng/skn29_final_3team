[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$OutputPath,
    [string]$BaselineVersion = '2026-07-29.1'
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Resolve-Path (Join-Path $databaseRoot '..\..')
Set-Location $repoRoot

if (git status --short) {
    throw 'Baseline export requires a clean Git worktree.'
}

$compose = Join-Path $databaseRoot 'compose.yml'
$sqlFiles = Get-ChildItem (Join-Path $databaseRoot 'sql') -File -Recurse -Filter '*.sql' | Sort-Object FullName
$lines = @(
    '# Synthetic DB environment baseline',
    '',
    "- ENV_BASELINE_VERSION: $BaselineVersion",
    "- BASE_BRANCH: $(git branch --show-current)",
    "- BASE_SHA: $(git rev-parse HEAD)",
    '- TIMEZONE: Asia/Seoul',
    '- SCHEMA_VERSION: 1.0.0',
    '- SEED_VERSION: 20260729',
    '- SCENARIO_VERSION: 1.0.0',
    '',
    '## Service contract',
    '',
    '| Service | Internal endpoint | Host port | Engine | DB / schema |',
    '|---|---|---:|---|---|',
    '| app-postgres | app-postgres:5432 | 15432 | PostgreSQL 16.13 | app_db / application schemas |',
    '| pms-postgres | pms-postgres:5432 | 15433 | PostgreSQL 16.13 | pms_db / public |',
    '| banquet-postgres | banquet-postgres:5432 | 15434 | PostgreSQL 16.13 | banquet_db / public |',
    '| pos-mysql | pos-mysql:3306 | 13306 | MySQL 8.4.6 | pos_db |',
    '| crm-mssql | crm-mssql:1433 | 11433 | SQL Server 2022 CU17 | crm_db / dbo |',
    '| facility-clickhouse | facility-clickhouse:8123 | 18123, 19000 | ClickHouse 24.8.4.13 | facility / facility |',
    '| trino | trino:8080 | 18080 | Trino 476 | source 5 catalog + serving |',
    '',
    '## Pinned images',
    '',
    '| Service | Image |',
    '|---|---|',
    '| app-postgres, pms-postgres, banquet-postgres | postgres:16.13-bookworm@sha256:472efd9a66f2b1f1a5aeb18b28de74332e6ef88c2b93a1a5d812fb6db67a5f60 |',
    '| pos-mysql | mysql:8.4.6@sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9 |',
    '| crm-mssql | mcr.microsoft.com/mssql/server:2022-CU17-ubuntu-22.04@sha256:d252932ef839c24c61c1139cc98f69c85ca774fa7c6bfaaa0015b7eb02b9dc87 |',
    '| facility-clickhouse | clickhouse/clickhouse-server:24.8.4.13@sha256:b2c51583a6df9c19d613b579a03f237b92e0dfc63433b3fdb567ce223e0fb0f7 |',
    '| trino | trinodb/trino:476@sha256:00125e40d063bc4816d165482f6044872b18b56026fb959d3b28ce1f96ffbbee |',
    '',
    '## Checksums',
    '',
    '| Path | SHA256 |',
    '|---|---|',
    "| infrastructure/database/compose.yml | $((Get-FileHash $compose -Algorithm SHA256).Hash) |"
)
foreach ($file in $sqlFiles) {
    $relative = $file.FullName.Substring($repoRoot.Path.Length + 1).Replace('\', '/')
    $lines += "| $relative | $((Get-FileHash $file.FullName -Algorithm SHA256).Hash) |"
}

$outputParent = Split-Path -Parent $OutputPath
if ($outputParent) { New-Item -ItemType Directory -Force -Path $outputParent | Out-Null }
Set-Content -LiteralPath $OutputPath -Value $lines -Encoding utf8
Write-Output "BASELINE_EXPORTED=$OutputPath"
