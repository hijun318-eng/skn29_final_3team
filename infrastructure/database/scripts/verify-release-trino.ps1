# 책임: repository deployment environment의 Trino principal을 process 환경으로만 전달하고,
# Python live verifier가 release-bound D0/D1 receipt를 생성하도록 호출한다.
[CmdletBinding()]
param(
    [string]$EnvFilePath,
    [Parameter(Mandatory)] [string]$ReleaseId,
    [Parameter(Mandatory)] [string]$EvidenceDirectory,
    [string[]]$RequiredRawCatalog = @('pms', 'crm', 'pos')
)

$ErrorActionPreference = 'Stop'
$databaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $databaseRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'deployment-environment.ps1')
$resolvedEnvFile = Resolve-RepositoryDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot
$values = Read-DeploymentEnvironment $resolvedEnvFile
Assert-DeploymentEnvironmentValues -Values $values -RequiredKeys @(
    'TRINO_PORT', 'TRINO_ADMIN_USER', 'TRINO_ADMIN_PASSWORD',
    'TRINO_TLS_CA_HOST_FILE'
)
$caFile = Assert-ExternalDeploymentFile -Values $values `
    -Key 'TRINO_TLS_CA_HOST_FILE' -RepositoryRoot $repoRoot
if ([string]$values['TRINO_ADMIN_USER'] -cne 'answervice_platform_admin') {
    throw 'Trino verification requires the configured platform admin identity.'
}
$port = 0
if (-not [int]::TryParse([string]$values['TRINO_PORT'], [ref]$port) -or
    $port -lt 1 -or $port -gt 65535) {
    throw 'TRINO_PORT is invalid.'
}
if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$') {
    throw 'ReleaseId format is invalid.'
}
$releaseMatches = @()
foreach ($directory in Get-ChildItem -LiteralPath (Join-Path $databaseRoot 'releases') -Directory) {
    $candidate = Join-Path $directory.FullName 'manifest.json'
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    $document = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$document.release_id -ceq $ReleaseId) { $releaseMatches += $candidate }
}
if ($releaseMatches.Count -ne 1) {
    throw "ReleaseId must resolve to exactly one manifest: $ReleaseId"
}
$evidenceRoot = [IO.Path]::GetFullPath($EvidenceDirectory)
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + `
    [IO.Path]::DirectorySeparatorChar
if (-not $evidenceRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'EvidenceDirectory must remain inside the repository.'
}
$outputPath = Join-Path $evidenceRoot 'trino-runtime-receipt.json'
$verifier = Join-Path $PSScriptRoot 'verify_trino_release.py'
$catalogDirectory = Join-Path $databaseRoot 'trino\etc\catalog'

# password와 CA path는 Python argv에 넣지 않는다. 호출 전 process 값만 잠시 바꾸고
# finally에서 원래 값으로 복원해 operator shell에 credential을 남기지 않는다.
$names = @(
    'ANSWERVICE_VERIFY_TRINO_URL', 'ANSWERVICE_VERIFY_TRINO_USER',
    'ANSWERVICE_VERIFY_TRINO_PASSWORD', 'ANSWERVICE_VERIFY_TRINO_CA_FILE',
    'ANSWERVICE_VERIFY_BASE_SHA', 'PYTHONDONTWRITEBYTECODE'
)
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $env:ANSWERVICE_VERIFY_TRINO_URL = "https://127.0.0.1:$port"
    $env:ANSWERVICE_VERIFY_TRINO_USER = [string]$values['TRINO_ADMIN_USER']
    $env:ANSWERVICE_VERIFY_TRINO_PASSWORD = [string]$values['TRINO_ADMIN_PASSWORD']
    $env:ANSWERVICE_VERIFY_TRINO_CA_FILE = $caFile
    $env:ANSWERVICE_VERIFY_BASE_SHA = (& git -C $repoRoot rev-parse HEAD).Trim()
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & python $verifier `
        --manifest $releaseMatches[0] `
        --catalog-directory $catalogDirectory `
        --required-raw-catalog @RequiredRawCatalog `
        --output $outputPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Trino release verification failed.'
    }
} finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
