# 책임: 수신한 private bundle의 checksum과 exact Git SHA를 검증하고, env의 host-file
# placeholder만 수신자 저장소 밖 절대경로로 바꿔 기존 설정을 덮어쓰지 않고 설치한다.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$BundleDirectory,
    [Parameter(Mandatory)] [string]$RepositoryPath,
    [string]$DeploymentRoot
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$expectedHostFileTargets = [ordered]@{
    TRINO_PASSWORD_DB_HOST_FILE = 'trino-password.db'
    TRINO_TLS_KEYSTORE_HOST_FILE = 'trino-keystore.p12'
    TRINO_TLS_CA_HOST_FILE = 'trino-ca.pem'
    DATAHUB_TLS_KEYSTORE_HOST_FILE = 'datahub-keystore.p12'
    DATAHUB_TLS_TRUSTSTORE_HOST_FILE = 'datahub-truststore.p12'
    DATAHUB_TLS_CA_HOST_FILE = 'datahub-ca.pem'
    AUTH_PRINCIPALS_HOST_FILE = 'auth-principals.json'
    SERVING_CATALOG_BOOTSTRAP_CREDENTIALS_HOST_FILE = 'serving-catalog-bootstrap.credentials'
    SERVING_CATALOG_TOKEN_PUBLIC_KEY_HOST_FILE = 'serving-catalog-token-public.pem'
    SERVING_CATALOG_TOKEN_PRIVATE_KEY_HOST_FILE = 'serving-catalog-token-private.pem'
}

function Resolve-ExistingDirectory {
    param([Parameter(Mandatory)] [string]$Path)

    if (-not [IO.Path]::IsPathRooted($Path) -or
        -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw 'Path must identify an existing absolute directory.'
    }
    return [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
}

function Test-PathInsideRoot {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Root
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    return $resolvedPath.Equals($resolvedRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $resolvedPath.StartsWith(
            $resolvedRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
}

function Invoke-GitText {
    param([Parameter(Mandatory)] [string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& git @Arguments 2>$null | ForEach-Object { [string]$_ })
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) { throw 'Required Git command failed.' }
    return $output
}

function Assert-Checksums {
    param(
        [Parameter(Mandatory)] [string]$Root,
        [Parameter(Mandatory)] [string]$ChecksumFile
    )

    if (-not (Test-Path -LiteralPath $ChecksumFile -PathType Leaf)) {
        throw 'Bundle checksum file is missing.'
    }
    $checksumPath = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ChecksumFile).Path)
    $declaredPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($line in Get-Content -LiteralPath $ChecksumFile -Encoding UTF8) {
        if ($line -notmatch '^([0-9a-f]{64}) \*(.+)$') {
            throw 'Bundle checksum file has an invalid line.'
        }
        $expected = $Matches[1]
        $relative = $Matches[2]
        if ([IO.Path]::IsPathRooted($relative)) {
            throw 'Bundle checksum path must be relative.'
        }
        $candidate = [IO.Path]::GetFullPath((Join-Path $Root ($relative.Replace('/', '\'))))
        if (-not (Test-PathInsideRoot -Path $candidate -Root $Root) -or
            -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw 'Bundle checksum references a missing or escaped file.'
        }
        if ($candidate.Equals($checksumPath, [StringComparison]::OrdinalIgnoreCase) -or
            -not $declaredPaths.Add($candidate)) {
            throw 'Bundle checksum contains a self-reference or duplicate path.'
        }
        $actual = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -cne $expected) {
            throw 'Bundle checksum verification failed.'
        }
    }
    $payloadFiles = @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force |
        Where-Object {
            -not $_.FullName.Equals($checksumPath, [StringComparison]::OrdinalIgnoreCase)
        })
    if ($declaredPaths.Count -ne $payloadFiles.Count) {
        throw 'Bundle checksum does not cover the complete payload.'
    }
    foreach ($payloadFile in $payloadFiles) {
        if (-not $declaredPaths.Contains([IO.Path]::GetFullPath($payloadFile.FullName))) {
            throw 'Bundle checksum does not cover the complete payload.'
        }
    }
}

$bundleRoot = Resolve-ExistingDirectory $BundleDirectory
$repoRoot = Resolve-ExistingDirectory $RepositoryPath
if (Test-PathInsideRoot -Path $bundleRoot -Root $repoRoot) {
    throw 'BundleDirectory must remain outside the repository.'
}
if (Test-Path -LiteralPath (Join-Path $bundleRoot '.INCOMPLETE')) {
    throw 'Bundle creation is incomplete.'
}
$bundleItem = Get-Item -LiteralPath $bundleRoot -Force
if (($bundleItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'BundleDirectory must not be a reparse point.'
}
$reparsePoint = Get-ChildItem -LiteralPath $bundleRoot -Recurse -Force |
    Where-Object {
        ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    } | Select-Object -First 1
if ($reparsePoint) {
    throw 'Bundle must not contain reparse points.'
}
$publicRoot = Resolve-ExistingDirectory (Join-Path $bundleRoot 'public')
$privateRoot = Resolve-ExistingDirectory (Join-Path $bundleRoot 'private')
$sourceSecretRoot = Resolve-ExistingDirectory (Join-Path $privateRoot 'secrets')
Assert-Checksums -Root $publicRoot -ChecksumFile (Join-Path $publicRoot 'checksums.sha256')
Assert-Checksums -Root $privateRoot `
    -ChecksumFile (Join-Path $privateRoot 'private-checksums.sha256')

$manifestPath = Join-Path $publicRoot 'release-manifest.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.schemaVersion -ne 1 -or
    [string]$manifest.mode -notin @('Fresh', 'Snapshot') -or
    [string]::IsNullOrWhiteSpace([string]$manifest.repository.sourceCommit)) {
    throw 'Release manifest is invalid.'
}
$headOutput = @(Invoke-GitText @('-C', $repoRoot, 'rev-parse', 'HEAD'))
if ($headOutput.Count -ne 1) { throw 'Git HEAD output is invalid.' }
$head = [string]$headOutput[0]
$status = @(Invoke-GitText @(
    '-C', $repoRoot, 'status', '--porcelain=v1', '--untracked-files=all'
))
if ($head -cne [string]$manifest.repository.sourceCommit -or $status.Count -ne 0) {
    throw 'Repository must be clean and checked out at the manifest source commit.'
}

if ([string]::IsNullOrWhiteSpace($DeploymentRoot)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw 'DeploymentRoot is required when LOCALAPPDATA is unavailable.'
    }
    $DeploymentRoot = Join-Path $env:LOCALAPPDATA 'Answervice'
}
if (-not [IO.Path]::IsPathRooted($DeploymentRoot)) {
    throw 'DeploymentRoot must be an absolute path.'
}
$resolvedDeploymentRoot = [IO.Path]::GetFullPath($DeploymentRoot)
if (Test-PathInsideRoot -Path $resolvedDeploymentRoot -Root $repoRoot) {
    throw 'DeploymentRoot must remain outside the repository.'
}
$deploymentDirectory = Join-Path $resolvedDeploymentRoot 'deployment'
$targetSecretRoot = Join-Path $resolvedDeploymentRoot 'secrets'
$targetEnvFile = Join-Path $deploymentDirectory 'answervice.env'
$sourceSecrets = @(Get-ChildItem -LiteralPath $sourceSecretRoot -File)
$sourceSecretNames = @($sourceSecrets | ForEach-Object { $_.Name } | Sort-Object)
$expectedNames = @($expectedHostFileTargets.Values | Sort-Object)
if (($sourceSecretNames -join "`n") -cne ($expectedNames -join "`n")) {
    throw 'Private bundle does not contain the exact expected secret file set.'
}
$templatePath = Join-Path $privateRoot 'answervice.env.template'
if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf)) {
    throw 'Private bundle is missing answervice.env.template.'
}
$envText = [IO.File]::ReadAllText($templatePath)
foreach ($entry in $expectedHostFileTargets.GetEnumerator()) {
    $key = [regex]::Escape([string]$entry.Key)
    $targetName = [regex]::Escape([string]$entry.Value)
    $pattern = "(?m)^$key=__ANSWERVICE_SECRET_ROOT__/$targetName`r?$"
    if ([regex]::Matches($envText, $pattern).Count -ne 1) {
        throw "Deployment env template has an invalid host-file entry '$($entry.Key)'."
    }
}
$portableSecretRoot = $targetSecretRoot.Replace('\', '/')
$envText = $envText.Replace('__ANSWERVICE_SECRET_ROOT__', $portableSecretRoot)
if ($envText.Contains('__ANSWERVICE_SECRET_ROOT__')) {
    throw 'Deployment env placeholder replacement did not complete.'
}
if (Test-Path -LiteralPath $targetEnvFile) {
    throw 'Target deployment env already exists; nothing was overwritten.'
}
foreach ($source in $sourceSecrets) {
    $target = Join-Path $targetSecretRoot $source.Name
    if (Test-Path -LiteralPath $target) {
        throw 'A target secret file already exists; nothing was overwritten.'
    }
}
New-Item -ItemType Directory -Force -Path $deploymentDirectory,$targetSecretRoot | Out-Null
foreach ($source in $sourceSecrets) {
    Copy-Item -LiteralPath $source.FullName -Destination (Join-Path $targetSecretRoot $source.Name)
}
[IO.File]::WriteAllText($targetEnvFile, $envText, [Text.UTF8Encoding]::new($false))

Write-Output 'HANDOFF_CONFIG_INSTALLED'
Write-Output "ENV_FILE|$targetEnvFile"
if (Test-Path -LiteralPath (Join-Path $privateRoot 'state') -PathType Container) {
    Write-Output "STATE_INPUT|$(Join-Path $privateRoot 'state')"
}
Write-Output 'NEXT|Follow public/HANDOFF.md; no service or database was started.'
