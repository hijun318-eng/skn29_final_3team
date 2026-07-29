[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$databaseRoot = $PSScriptRoot
$composeFile = Join-Path $databaseRoot 'compose.yml'
$localEnv = Join-Path $databaseRoot '.env'

if (-not (Test-Path -LiteralPath $localEnv)) {
    throw '.env is missing. Nothing was reset.'
}
if (-not $Force) {
    $answer = Read-Host 'Delete only hotel-synthetic-db volumes? Type YES'
    if ($answer -ne 'YES') { return }
}

& docker compose --env-file $localEnv -f $composeFile down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'docker compose down failed.' }
& (Join-Path $databaseRoot 'scripts\initialize.ps1')
