# 책임: 확인된 Compose project label에 속한 volume만 명시 승인 후 삭제한다.
# project identity를 해석하지 못하면 어떤 container나 volume도 변경하지 않는다.
[CmdletBinding()]
param(
    [switch]$Force,
    [string]$EnvFilePath
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $databaseRoot)
$composeFile = Join-Path $databaseRoot 'compose.yml'
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
Disable-ImplicitComposeEnvironment
$resolvedEnvFile = Resolve-RepositoryDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvFile)

$resolved = & docker compose @composeEnvArguments -f $composeFile config --format json |
    ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $resolved.name) {
    throw 'Compose project identity could not be resolved; nothing was reset.'
}
if (-not $Force) {
    $answer = Read-Host "Delete only '$($resolved.name)' Compose volumes? Type YES"
    if ($answer -ne 'YES') { return }
}

# Compose labels define the deletion boundary. No path, wildcard, or global
# Docker volume cleanup is used here.
& docker compose @composeEnvArguments -f $composeFile down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'docker compose down failed.' }
& (Join-Path $PSScriptRoot 'start.ps1')
