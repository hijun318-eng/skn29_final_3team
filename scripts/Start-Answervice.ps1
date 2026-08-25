[CmdletBinding()]
param(
    [string]$EnvFilePath = (Join-Path $env:LOCALAPPDATA "Answervice\deployment\answervice.env"),
    [string]$BackendEnvFilePath = (Join-Path $env:LOCALAPPDATA "Answervice\deployment\backend.env"),
    [switch]$SkipInfrastructure
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "compose.yml"
$adminComposeFile = Join-Path $repoRoot "admin\compose.yml"

if (-not (Test-Path -LiteralPath $EnvFilePath)) {
    throw "Deployment environment file not found: $EnvFilePath"
}
$composeEnvArguments = @("--env-file", $EnvFilePath)
if (Test-Path -LiteralPath $BackendEnvFilePath) {
    $composeEnvArguments += @("--env-file", $BackendEnvFilePath)
}

docker context use desktop-linux | Out-Host
if ((docker context show).Trim() -ne "desktop-linux") {
    throw "Docker context must be desktop-linux."
}

if (-not $SkipInfrastructure) {
    $infrastructureStart = Join-Path $repoRoot "infrastructure\Start-Answervice.ps1"
    if (Test-Path -LiteralPath $infrastructureStart) {
        & $infrastructureStart -EnvFilePath $EnvFilePath
    }
}

docker --context desktop-linux compose --project-name answervice @composeEnvArguments -f $composeFile --profile full --profile ml-e2e up -d --build backend frontend ml-runtime rag-api rag-local-answer
docker --context desktop-linux compose --project-name answervice-admin @composeEnvArguments -f $adminComposeFile up -d

Write-Host "Agent: http://127.0.0.1:13000/agent"
Write-Host "Admin: http://127.0.0.1:28080/"
