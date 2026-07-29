[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$databaseDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $databaseDirectory

try {
    & docker compose down
    if ($LASTEXITCODE -ne 0) {
        throw 'Database shutdown failed.'
    }
}
finally {
    Pop-Location
}
