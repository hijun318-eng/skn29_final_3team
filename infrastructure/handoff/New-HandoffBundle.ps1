# 책임: 최종 push된 release와 외부 deployment material을 검증하고, secret 값을
# 출력하지 않은 public receipt와 암호화 전 private 전달 묶음을 저장소 밖에 생성한다.
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Fresh', 'Snapshot')]
    [string]$Mode,

    [Parameter(Mandatory)]
    [string]$EnvFilePath,

    [string]$OutputRoot,
    [string]$SnapshotInputRoot,
    [switch]$PreflightOnly,
    [switch]$AllowRepositoryLocalDevelopment,
    [switch]$AcknowledgePlaintextSecrets
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$composeFile = Join-Path $repoRoot 'compose.yml'
$deploymentHelper = Join-Path $repoRoot 'infrastructure/database/scripts/deployment-environment.ps1'
. $deploymentHelper
Disable-ImplicitComposeEnvironment

$hostFileTargets = [ordered]@{
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

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)] [string]$Command,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $Command @Arguments 2>$null | ForEach-Object { [string]$_ })
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "Required command failed: $Command"
    }
    [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

function Resolve-AbsoluteDirectory {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [switch]$MustExist
    )

    if (-not (Test-FullyQualifiedFileSystemPath $Path)) {
        throw 'Directory path must be absolute.'
    }
    if ($MustExist -and -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw 'Required directory does not exist.'
    }
    if ($MustExist) {
        return [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    }
    return [IO.Path]::GetFullPath($Path)
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

function Get-RelativePathUnderRoot {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Root
    )

    $resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $prefix = $resolvedRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'File escaped the expected bundle root.'
    }
    return $resolvedPath.Substring($prefix.Length).Replace('\', '/')
}

function Write-ChecksumFile {
    param(
        [Parameter(Mandatory)] [string]$Root,
        [Parameter(Mandatory)] [string]$OutputPath,
        [Parameter(Mandatory)] [string[]]$Files
    )

    $lines = foreach ($file in $Files | Sort-Object) {
        $relative = Get-RelativePathUnderRoot -Path $file -Root $Root
        $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash *$relative"
    }
    [IO.File]::WriteAllLines($OutputPath, $lines, [Text.UTF8Encoding]::new($false))
}

function Get-ReleaseState {
    $status = Invoke-NativeText -Command git -Arguments @(
        '-C', $repoRoot, 'status', '--porcelain=v1', '--untracked-files=all'
    )
    if ($status.Output.Count -ne 0) {
        throw 'Repository is not clean; commit or remove every tracked and untracked change first.'
    }

    $branch = Invoke-NativeText -Command git -Arguments @(
        '-C', $repoRoot, 'symbolic-ref', '--quiet', '--short', 'HEAD'
    )
    $commit = Invoke-NativeText -Command git -Arguments @('-C', $repoRoot, 'rev-parse', 'HEAD')
    $upstream = Invoke-NativeText -Command git -Arguments @(
        '-C', $repoRoot, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}'
    )
    $branchName = [string]$branch.Output[0]
    $commitSha = [string]$commit.Output[0]
    $upstreamName = [string]$upstream.Output[0]

    $tracking = Invoke-NativeText -Command git -Arguments @(
        '-C', $repoRoot, 'rev-list', '--left-right', '--count', "$upstreamName...HEAD"
    )
    $counts = ([string]$tracking.Output[0]).Trim() -split '\s+'
    if ($counts.Count -ne 2 -or $counts[0] -ne '0' -or $counts[1] -ne '0') {
        throw 'HEAD and the local upstream tracking reference do not match.'
    }

    $upstreamParts = $upstreamName -split '/', 2
    if ($upstreamParts.Count -ne 2) {
        throw 'Upstream must identify a remote branch.'
    }
    $previousPrompt = $env:GIT_TERMINAL_PROMPT
    $env:GIT_TERMINAL_PROMPT = '0'
    try {
        $remote = Invoke-NativeText -Command git -Arguments @(
            '-C', $repoRoot, 'ls-remote', '--heads', $upstreamParts[0],
            "refs/heads/$($upstreamParts[1])"
        )
    } finally {
        $env:GIT_TERMINAL_PROMPT = $previousPrompt
    }
    if ($remote.Output.Count -ne 1 -or
        (([string]$remote.Output[0]) -split '\s+')[0] -cne $commitSha) {
        throw 'Remote branch SHA does not match HEAD.'
    }

    [ordered]@{
        branch = $branchName
        sourceCommit = $commitSha
        upstream = $upstreamName
    }
}

function Get-RuntimeState {
    $dockerVersion = Invoke-NativeText -Command docker -Arguments @(
        'version', '--format', '{{.Client.Version}}|{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}'
    )
    $parts = ([string]$dockerVersion.Output[0]) -split '\|'
    if ($parts.Count -ne 4) {
        throw 'Docker version output did not match the expected contract.'
    }
    $composeVersion = Invoke-NativeText -Command docker -Arguments @('compose', 'version', '--short')
    [ordered]@{
        dockerClientVersion = $parts[0]
        dockerServerVersion = $parts[1]
        dockerServerOs = $parts[2]
        dockerServerArch = $parts[3]
        composeVersion = [string]$composeVersion.Output[0]
    }
}

$resolvedEnvFile = Resolve-ExplicitDeploymentEnvFile `
    -Path $EnvFilePath -RepositoryRoot $repoRoot `
    -AllowRepositoryLocalDevelopment:$AllowRepositoryLocalDevelopment
if ([string]::IsNullOrWhiteSpace($resolvedEnvFile)) {
    throw 'EnvFilePath must identify an explicit deployment env file.'
}
$values = Read-DeploymentEnvironment $resolvedEnvFile
foreach ($key in $values.Keys) {
    $ambientValue = [Environment]::GetEnvironmentVariable([string]$key, 'Process')
    if ($null -ne $ambientValue -and $ambientValue -cne [string]$values[$key]) {
        throw "Process environment overrides deployment key '$key'; remove the ambient override."
    }
}
$resolvedHostFiles = [ordered]@{}
$hostFileReport = @()
foreach ($entry in $hostFileTargets.GetEnumerator()) {
    $resolved = Assert-ExplicitDeploymentFile -Values $values -Key $entry.Key `
        -RepositoryRoot $repoRoot `
        -AllowRepositoryLocalDevelopment:$AllowRepositoryLocalDevelopment
    $item = Get-Item -LiteralPath $resolved -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Deployment host file '$($entry.Key)' must not be a reparse point."
    }
    if ($item.Length -eq 0) {
        throw "Deployment host file '$($entry.Key)' must not be empty."
    }
    $resolvedHostFiles[$entry.Key] = $resolved
    $hostFileReport += [ordered]@{
        key = $entry.Key
        defined = $true
        absolute = $true
        exists = $true
        outsideRepository = -not (Test-PathInsideRoot -Path $resolved -Root $repoRoot)
    }
}

$duplicateHostFiles = @($resolvedHostFiles.GetEnumerator() |
    Group-Object -Property Value |
    Where-Object { $_.Count -gt 1 })
foreach ($duplicate in $duplicateHostFiles) {
    $duplicateKeys = @($duplicate.Group | ForEach-Object { [string]$_.Key } | Sort-Object)
    $allowedCaKeys = @('DATAHUB_TLS_CA_HOST_FILE', 'TRINO_TLS_CA_HOST_FILE') | Sort-Object
    if (($duplicateKeys -join "`n") -cne ($allowedCaKeys -join "`n")) {
        throw 'Only the documented Trino/DataHub CA pair may share one host file.'
    }
}

$releaseState = Get-ReleaseState
$runtimeState = Get-RuntimeState
$previousDisableEnv = $env:COMPOSE_DISABLE_ENV_FILE
$env:COMPOSE_DISABLE_ENV_FILE = '1'
try {
    Invoke-NativeText -Command docker -Arguments @(
        'compose', '--env-file', $resolvedEnvFile, '-f', $composeFile,
        '--profile', 'full', 'config', '--quiet'
    ) | Out-Null
} finally {
    $env:COMPOSE_DISABLE_ENV_FILE = $previousDisableEnv
}

$resolvedSnapshotRoot = $null
$snapshotReceipt = $null
if ($Mode -eq 'Fresh' -and -not [string]::IsNullOrWhiteSpace($SnapshotInputRoot)) {
    throw 'Fresh mode must not receive SnapshotInputRoot.'
}
if ($Mode -eq 'Snapshot') {
    if ([string]::IsNullOrWhiteSpace($SnapshotInputRoot)) {
        throw 'Snapshot mode requires SnapshotInputRoot.'
    }
    $resolvedSnapshotRoot = Resolve-AbsoluteDirectory -Path $SnapshotInputRoot -MustExist
    if (Test-PathInsideRoot -Path $resolvedSnapshotRoot -Root $repoRoot) {
        throw 'SnapshotInputRoot must remain outside the repository.'
    }
    $receiptPath = Join-Path $resolvedSnapshotRoot 'snapshot-receipt.json'
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw 'Snapshot input is missing snapshot-receipt.json.'
    }
    $snapshotReceipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
    if ($snapshotReceipt.schemaVersion -ne 1 -or
        [string]$snapshotReceipt.sourceCommit -cne [string]$releaseState.sourceCommit -or
        [string]$snapshotReceipt.composeProject -cne 'answervice' -or
        [string]::IsNullOrWhiteSpace([string]$snapshotReceipt.quiescenceId) -or
        $snapshotReceipt.quiesced -ne $true -or
        $snapshotReceipt.nativeVerificationPassed -ne $true -or
        $snapshotReceipt.cleanRestoreRehearsalPassed -ne $true) {
        throw 'Snapshot receipt does not match the release or verified quiesced contract.'
    }
    $reparsePoint = Get-ChildItem -LiteralPath $resolvedSnapshotRoot -Recurse -Force |
        Where-Object {
            ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        } | Select-Object -First 1
    if ($reparsePoint) {
        throw 'Snapshot input must not contain reparse points.'
    }
    $snapshotArtifacts = @($snapshotReceipt.artifacts)
    if ($snapshotArtifacts.Count -eq 0) {
        throw 'Snapshot receipt must declare at least one artifact.'
    }
    $seenArtifactPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($artifact in $snapshotArtifacts) {
        $relativePath = [string]$artifact.relativePath
        if ([string]::IsNullOrWhiteSpace([string]$artifact.kind) -or
            [string]::IsNullOrWhiteSpace([string]$artifact.service) -or
            [string]::IsNullOrWhiteSpace($relativePath) -or
            [IO.Path]::IsPathRooted($relativePath)) {
            throw 'Snapshot artifact paths must be non-empty relative paths.'
        }
        $artifactPath = [IO.Path]::GetFullPath((Join-Path $resolvedSnapshotRoot $relativePath))
        if ($artifactPath.Equals($resolvedSnapshotRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-PathInsideRoot -Path $artifactPath -Root $resolvedSnapshotRoot) -or
            -not (Test-Path -LiteralPath $artifactPath)) {
            throw 'Snapshot receipt references a missing or escaped artifact.'
        }
        if (-not $seenArtifactPaths.Add($artifactPath)) {
            throw 'Snapshot receipt contains a duplicate artifact path.'
        }
    }
}

$uniqueHostFileCount = @($resolvedHostFiles.Values | Sort-Object -Unique).Count
if ($PreflightOnly) {
    [ordered]@{
        status = 'HANDOFF_PREFLIGHT_READY'
        mode = $Mode
        sourceCommit = $releaseState.sourceCommit
        branch = $releaseState.branch
        upstream = $releaseState.upstream
        requiredHostFileEntries = $hostFileTargets.Count
        uniqueHostFiles = $uniqueHostFileCount
        snapshotValidated = ($Mode -eq 'Snapshot')
        runtime = $runtimeState
    } | ConvertTo-Json -Depth 4
    return
}

if (-not $AcknowledgePlaintextSecrets) {
    throw 'Collecting requires -AcknowledgePlaintextSecrets because private output is unencrypted.'
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    throw 'Collecting requires OutputRoot.'
}
$resolvedOutputRoot = Resolve-AbsoluteDirectory -Path $OutputRoot
if (Test-PathInsideRoot -Path $resolvedOutputRoot -Root $repoRoot) {
    throw 'OutputRoot must remain outside the repository.'
}
if (-not (Test-Path -LiteralPath $resolvedOutputRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $resolvedOutputRoot | Out-Null
}
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$shortSha = ([string]$releaseState.sourceCommit).Substring(0, 12)
$bundleName = "answervice-$shortSha-$timestamp-$($Mode.ToLowerInvariant())"
$bundleRoot = Join-Path $resolvedOutputRoot $bundleName
if (Test-Path -LiteralPath $bundleRoot) {
    throw 'Generated bundle directory already exists; nothing was overwritten.'
}
$publicRoot = Join-Path $bundleRoot 'public'
$privateRoot = Join-Path $bundleRoot 'private'
$secretRoot = Join-Path $privateRoot 'secrets'
New-Item -ItemType Directory -Path $publicRoot,$privateRoot,$secretRoot | Out-Null
[IO.File]::WriteAllText(
    (Join-Path $bundleRoot '.INCOMPLETE'),
    "Bundle creation did not complete.`r`n",
    [Text.UTF8Encoding]::new($false)
)

Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') `
    -Destination (Join-Path $publicRoot 'HANDOFF.md')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'AI_SETUP_AGENT.md') `
    -Destination (Join-Path $publicRoot 'AI_SETUP_AGENT.md')
$envText = [IO.File]::ReadAllText($resolvedEnvFile)
if ($envText.Contains('__ANSWERVICE_SECRET_ROOT__')) {
    throw 'Deployment env already contains the reserved handoff placeholder.'
}
foreach ($entry in $hostFileTargets.GetEnumerator()) {
    $targetName = [string]$entry.Value
    Copy-Item -LiteralPath $resolvedHostFiles[$entry.Key] `
        -Destination (Join-Path $secretRoot $targetName)
    $pattern = "(?m)^\s*(?:export\s+)?$([regex]::Escape([string]$entry.Key))=.*$"
    if (-not [regex]::IsMatch($envText, $pattern)) {
        throw "Deployment env no longer contains '$($entry.Key)'."
    }
    $replacement = "$($entry.Key)=__ANSWERVICE_SECRET_ROOT__/$targetName"
    $envText = [regex]::Replace($envText, $pattern, $replacement)
}
[IO.File]::WriteAllText(
    (Join-Path $privateRoot 'answervice.env.template'),
    $envText,
    [Text.UTF8Encoding]::new($false)
)
[IO.File]::WriteAllText(
    (Join-Path $privateRoot 'SENSITIVE.txt'),
    "CONFIDENTIAL: contains credentials, keys, and possibly runtime data. Transfer only through an approved encrypted channel.`r`n",
    [Text.UTF8Encoding]::new($false)
)

if ($Mode -eq 'Snapshot') {
    $stateRoot = Join-Path $privateRoot 'state'
    New-Item -ItemType Directory -Path $stateRoot | Out-Null
    Get-ChildItem -LiteralPath $resolvedSnapshotRoot -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $stateRoot -Recurse
    }
}

$manifest = [ordered]@{
    schemaVersion = 1
    classification = 'PUBLIC_RECEIPT_PRIVATE_PAYLOAD_SEPARATE'
    mode = $Mode
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    repository = [ordered]@{
        branch = $releaseState.branch
        sourceCommit = $releaseState.sourceCommit
        upstream = $releaseState.upstream
        clean = $true
        remoteHeadMatches = $true
    }
    runtime = $runtimeState
    compose = [ordered]@{
        project = if ($values.ContainsKey('COMPOSE_PROJECT_NAME')) {
            [string]$values['COMPOSE_PROJECT_NAME']
        } else {
            'answervice'
        }
        profile = 'full'
        configValidated = $true
    }
    hostFiles = [ordered]@{
        requiredEntryCount = $hostFileTargets.Count
        uniqueSourceCount = $uniqueHostFileCount
        entries = $hostFileReport
    }
    data = [ordered]@{
        included = ($Mode -eq 'Snapshot')
        parityClaimed = ($Mode -eq 'Snapshot')
        receipt = if ($Mode -eq 'Snapshot') {
            'private/state/snapshot-receipt.json'
        } else {
            $null
        }
    }
}
$manifestPath = Join-Path $publicRoot 'release-manifest.json'
[IO.File]::WriteAllText(
    $manifestPath,
    (($manifest | ConvertTo-Json -Depth 8) + "`r`n"),
    [Text.UTF8Encoding]::new($false)
)

$publicFiles = @(
    Join-Path $publicRoot 'HANDOFF.md'
    Join-Path $publicRoot 'AI_SETUP_AGENT.md'
    $manifestPath
)
Write-ChecksumFile -Root $publicRoot `
    -OutputPath (Join-Path $publicRoot 'checksums.sha256') -Files $publicFiles
$privateFiles = @(Get-ChildItem -LiteralPath $privateRoot -Recurse -File |
    ForEach-Object { $_.FullName })
Write-ChecksumFile -Root $privateRoot `
    -OutputPath (Join-Path $privateRoot 'private-checksums.sha256') -Files $privateFiles
Remove-Item -LiteralPath (Join-Path $bundleRoot '.INCOMPLETE')
Write-Output "HANDOFF_READY|$bundleRoot"
