[CmdletBinding()]
param([string]$TrinoContainer = 'hotel-synthetic-db-trino-1')

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$contract = Get-Content -Raw -Encoding UTF8 (
    Join-Path $databaseRoot '..\..\src\data\i3_contract.v1.json'
) | ConvertFrom-Json

function Get-TrinoCanonical {
    param([Parameter(Mandatory)] [string]$Query)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $rows = & docker exec $TrinoContainer trino `
            --server http://localhost:8080 `
            --user hotel_synthetic_verify `
            --output-format TSV `
            --execute $Query 2>$null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) { throw 'Trino query failed.' }
    return ((@($rows) | ForEach-Object { $_.Trim().Replace("`t", '|') }) -join "`n") + "`n"
}

function Get-Sha256 {
    param([Parameter(Mandatory)] [string]$Value)

    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    return ([BitConverter]::ToString(
        [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    ) -replace '-', '').ToLowerInvariant()
}

foreach ($check in $contract.catalog_checks) {
    $hash = Get-Sha256 (Get-TrinoCanonical $check.query)
    if ($hash -ne $check.sha256) {
        throw "Catalog hash mismatch for $($check.source_id)."
    }
    Write-Output "I3_CATALOG_HASH_VERIFIED|$($check.source_id)|$hash"
}

foreach ($fixture in $contract.gold_fixtures) {
    $join = $contract.approved_joins | Where-Object join_id -eq $fixture.join_id
    $relativeQuery = $join.sql_file.Replace('infrastructure/database/', '')
    $query = Get-Content -Raw -Encoding UTF8 (Join-Path $databaseRoot $relativeQuery)
    $hash = Get-Sha256 (Get-TrinoCanonical $query)
    if ($hash -ne $fixture.sha256) {
        throw "Gold hash mismatch for $($fixture.id)."
    }
    Write-Output "I3_GOLD_HASH_VERIFIED|$($fixture.id)|$hash"
}

Write-Output 'I3_DATABASE_CONTRACT_VERIFIED'
