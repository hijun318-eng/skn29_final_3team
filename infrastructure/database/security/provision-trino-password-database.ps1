# 책임: 외부 deployment credential로 Trino 483 PBKDF2 password database를 원자
# 생성한다. canonical identity·강도·외부 경로 검증 실패 시 기존 파일을 덮지 않는다.
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [string]$EnvPath,
    [Parameter(Mandatory)] [string]$PasswordDatabasePath
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot '..\..\..'))
. (Join-Path $scriptRoot '../scripts/deployment-environment.ps1')
$resolvedEnvPath = Resolve-ExternalDeploymentEnvFile `
    -Path $EnvPath -RepositoryRoot $repoRoot
$values = Read-DeploymentEnvironment $resolvedEnvPath
$definitions = @(
    [ordered]@{
        user_key = 'TRINO_ADMIN_USER'
        password_key = 'TRINO_ADMIN_PASSWORD'
        expected_user = 'answervice_platform_admin'
    },
    [ordered]@{
        user_key = 'TRINO_RUNTIME_USER'
        password_key = 'TRINO_RUNTIME_PASSWORD'
        expected_user = 'answervice_runtime'
    },
    [ordered]@{
        user_key = 'TRINO_DATAHUB_USER'
        password_key = 'TRINO_DATAHUB_PASSWORD'
        expected_user = 'datahub_ingestion'
    }
)
Assert-DeploymentEnvironmentValues -Values $values -RequiredKeys @(
    $definitions | ForEach-Object { $_.user_key; $_.password_key }
)

$resolvedPasswordPath = [IO.Path]::GetFullPath($PasswordDatabasePath)
$passwordParent = Split-Path -Parent $resolvedPasswordPath
if (-not (Test-FullyQualifiedFileSystemPath $PasswordDatabasePath) -or
    -not (Test-Path -LiteralPath $passwordParent -PathType Container)) {
    throw 'PasswordDatabasePath must be absolute and its parent directory must exist.'
}
$repositoryPrefix = $repoRoot.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
if ($resolvedPasswordPath.StartsWith(
    $repositoryPrefix,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw 'PasswordDatabasePath must remain outside the repository.'
}

# Trino 483의 file authenticator는 PBKDF2WithHmacSHA1 형식을 읽는다. 충분한
# iteration과 매 identity별 random salt를 사용하고 plaintext는 파일에 기록하지 않는다.
$iterations = 210000
$passwords = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$lines = foreach ($definition in $definitions) {
    $username = [string]$values[$definition.user_key]
    $password = [string]$values[$definition.password_key]
    if ($username -cne $definition.expected_user -or
        $username -notmatch '^[A-Za-z_][A-Za-z0-9_]{2,63}$') {
        throw "Deployment identity '$($definition.user_key)' does not match the Trino ACL."
    }
    if ($password.Length -lt 12) {
        throw "Deployment secret '$($definition.password_key)' must contain at least 12 characters."
    }
    if (-not $passwords.Add($password)) {
        throw 'Trino principals must not share a password.'
    }

    $salt = [byte[]]::new(16)
    # Windows PowerShell 5.1의 .NET Framework에도 존재하는 instance API를 써서
    # 운영 host version과 무관하게 CSPRNG salt를 생성한다.
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($salt) } finally { $generator.Dispose() }
    $derive = [Security.Cryptography.Rfc2898DeriveBytes]::new(
        $password,
        $salt,
        $iterations,
        [Security.Cryptography.HashAlgorithmName]::SHA1
    )
    try { $hash = $derive.GetBytes(64) } finally { $derive.Dispose() }
    $saltHex = ([BitConverter]::ToString($salt)).Replace('-', '').ToLowerInvariant()
    $hashHex = ([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
    "$username`:$iterations`:$saltHex`:$hashHex"
}

if ($PSCmdlet.ShouldProcess($resolvedPasswordPath, 'Replace Trino password database')) {
    $temporaryPath = Join-Path $passwordParent (
        ".trino-password-$([guid]::NewGuid().ToString('N')).tmp"
    )
    try {
        [IO.File]::WriteAllLines(
            $temporaryPath,
            $lines,
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporaryPath -Destination $resolvedPasswordPath -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

[ordered]@{
    status = 'PROVISIONED'
    principal_count = $definitions.Count
    hash_contract = 'PBKDF2WithHmacSHA1-210000'
} | ConvertTo-Json -Compress
