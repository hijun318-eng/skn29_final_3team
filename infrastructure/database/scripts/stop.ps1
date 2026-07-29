$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $databaseRoot 'compose.yml'
$localEnv = Join-Path $databaseRoot '.env'

if (-not (Test-Path -LiteralPath $localEnv)) {
    throw '.env is missing. Nothing was stopped.'
}

& docker compose --env-file $localEnv -f $composeFile down
if ($LASTEXITCODE -ne 0) { throw 'docker compose down failed.' }
