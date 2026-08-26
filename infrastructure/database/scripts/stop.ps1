# 책임: repository deployment environment가 선택한 Compose project의 service만
# 중지하고 volume은 보존한다. project 해석이 실패하면 아무것도 중지하지 않는다.
[CmdletBinding()]
param([string]$EnvFilePath)

$ErrorActionPreference = 'Stop'
# Stop is intentionally non-destructive: it targets the configured Compose
# project and leaves all volumes for an explicit reset or approved backup flow.
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
    throw 'Compose project identity could not be resolved; nothing was stopped.'
}

& docker compose @composeEnvArguments -f $composeFile down
if ($LASTEXITCODE -ne 0) { throw 'docker compose down failed.' }
