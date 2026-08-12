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

Write-Output 'I3_DATABASE_CONTRACT_VERIFIED'
