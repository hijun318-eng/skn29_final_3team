# 책임: 운영 외부 또는 명시적 gitignored 개발 경로에 release principal의 PBKDF2
# verifier를 생성·회전한다. 묵시적 local fallback과 약한 credential은 쓰기 전에 거절한다.
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$EnvPath,
    [Parameter(Mandatory)]
    [string]$PrincipalPath,
    [string]$AnalystUsername,
    [ValidateSet('analyst', 'report_admin', 'data_admin', 'platform_admin')]
    [string]$AnalystRole,
    [int]$SessionTtlSeconds = 0,
    [switch]$PromptAnalystPassword,
    [switch]$PromptReportAdminPassword,
    [switch]$AllowRepositoryLocalDevelopment
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot '..\..\..'))
. (Join-Path $scriptRoot '../scripts/deployment-environment.ps1')
$resolvedEnvPath = Resolve-ExplicitDeploymentEnvFile `
    -Path $EnvPath -RepositoryRoot $repoRoot `
    -AllowRepositoryLocalDevelopment:$AllowRepositoryLocalDevelopment
$resolvedPrincipalPath = [IO.Path]::GetFullPath($PrincipalPath)
$principalParent = Split-Path -Parent $resolvedPrincipalPath
if (-not (Test-FullyQualifiedFileSystemPath $PrincipalPath) -or
    -not (Test-Path -LiteralPath $principalParent -PathType Container)) {
    throw 'PrincipalPath must be an absolute path whose parent directory already exists.'
}
$repositoryPrefix = $repoRoot.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
if ($resolvedPrincipalPath.StartsWith(
    $repositoryPrefix,
    [StringComparison]::OrdinalIgnoreCase
)) {
    if (-not $AllowRepositoryLocalDevelopment) {
        throw 'Repository-local PrincipalPath requires -AllowRepositoryLocalDevelopment.'
    }
    & git -C $repoRoot check-ignore -q -- $resolvedPrincipalPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Repository-local PrincipalPath must be covered by .gitignore.'
    }
}
$envText = [IO.File]::ReadAllText($resolvedEnvPath)

# Reads one exact dotenv key. Regex is limited to configuration syntax and is
# never used for natural-language routing or SQL validation.
function Read-EnvValue([string]$Name) {
    $match = [regex]::Match($envText, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return ''
}

# 동일 key의 모든 기존 entry를 같은 opaque value로 정규화한다. MatchEvaluator를
# 사용하므로 password 안의 '$'도 정규식 replacement group으로 재해석되지 않는다.
function Set-EnvValue([string]$Name, [string]$Value) {
    $pattern = "(?m)^$([regex]::Escape($Name))=.*$"
    if ([regex]::IsMatch($script:envText, $pattern)) {
        $replacement = "$Name=$Value"
        $script:envText = [regex]::Replace(
            $script:envText,
            $pattern,
            { param($match) $replacement }
        )
    } else {
        $script:envText = $script:envText.TrimEnd("`r", "`n") + "`r`n$Name=$Value`r`n"
    }
}

# Cryptographically secure random bytes are encoded without padding so the
# resulting value is safe in both dotenv files and JSON secrets.
function New-RandomValue([int]$ByteCount = 32) {
    $bytes = [byte[]]::new($ByteCount)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($bytes)
    $generator.Dispose()
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# PBKDF2 parameters are persisted with the digest so iteration upgrades can be
# performed account-by-account without accepting a plaintext fallback.
function Get-PasswordHash([string]$Password, [byte[]]$Salt, [int]$Iterations) {
    $derive = [Security.Cryptography.Rfc2898DeriveBytes]::new(
        $Password,
        $Salt,
        $Iterations,
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try { return ([BitConverter]::ToString($derive.GetBytes(32))).Replace('-', '').ToLowerInvariant() }
    finally { $derive.Dispose() }
}

# 계정 회전 모드는 username·Role만 일반 parameter로 받고 password는 secure prompt로만
# 입력한다. 원문 password가 argv, process 목록, script log에 남지 않게 한 뒤 외부 env와
# verifier를 같은 실행에서 갱신한다. 기본 모드는 기존 외부 env만 읽는다.
if ($AnalystUsername) {
    Set-EnvValue 'ANALYST_LOGIN_ID' $AnalystUsername.ToLowerInvariant()
}
if ($AnalystRole) {
    Set-EnvValue 'ANALYST_LOGIN_ROLE' $AnalystRole
}
if ($SessionTtlSeconds) {
    if ($SessionTtlSeconds -lt 900 -or $SessionTtlSeconds -gt 86400) {
        throw 'SessionTtlSeconds must be between 900 and 86400.'
    }
    Set-EnvValue 'AUTH_SESSION_TTL_SECONDS' ([string]$SessionTtlSeconds)
}
function Read-PasswordIntoEnvironment([string]$Prompt, [string]$EnvironmentKey) {
    while ($true) {
        $securePassword = Read-Host $Prompt -AsSecureString
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        try {
            $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
            if ($plainPassword -and $plainPassword.Length -ge 12) {
                Set-EnvValue $EnvironmentKey $plainPassword
                return
            }
            Write-Warning "$Prompt must contain at least 12 characters; try again."
        } finally {
            if ($passwordPointer -ne [IntPtr]::Zero) {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
            }
            $plainPassword = $null
            $securePassword = $null
        }
    }
}
if ($PromptAnalystPassword) {
    Read-PasswordIntoEnvironment 'Analyst password' 'ANALYST_LOGIN_PASSWORD'
}
if ($PromptReportAdminPassword) {
    Read-PasswordIntoEnvironment 'Report admin password' 'REPORT_ADMIN_LOGIN_PASSWORD'
}

# Login ID와 raw password를 일반 command parameter로 받지 않는다. 보호된 외부 env 또는
# 위 secure prompt에서만 읽고 principal 파일에는 PBKDF2 verifier만 기록한다.
$sessionSecret = Read-EnvValue 'AUTH_SESSION_SECRET'
if (-not $sessionSecret -or $sessionSecret.StartsWith('CHANGE_ME_')) {
    $sessionSecret = New-RandomValue
    Set-EnvValue 'AUTH_SESSION_SECRET' $sessionSecret
}
Set-EnvValue 'AUTH_PRINCIPALS_HOST_FILE' $resolvedPrincipalPath

$definitions = @(
    [ordered]@{
        username_env = 'ANALYST_LOGIN_ID'
        password_env = 'ANALYST_LOGIN_PASSWORD'
        role_env = 'ANALYST_LOGIN_ROLE'
        default_role = 'analyst'
    },
    [ordered]@{
        username_env = 'REPORT_ADMIN_LOGIN_ID'
        password_env = 'REPORT_ADMIN_LOGIN_PASSWORD'
        role_env = $null
        default_role = 'report_admin'
    }
)
$allowedRoles = @('analyst', 'report_admin', 'data_admin', 'platform_admin')
$existing = @()
if (Test-Path -LiteralPath $resolvedPrincipalPath) {
    try { $existing = @((Get-Content -Raw -LiteralPath $resolvedPrincipalPath | ConvertFrom-Json)) }
    catch { $existing = @() }
}
$iterations = 210000
$principals = foreach ($definition in $definitions) {
    $username = (Read-EnvValue $definition.username_env).ToLowerInvariant()
    $password = Read-EnvValue $definition.password_env
    $configuredRole = if ($definition.role_env) { Read-EnvValue $definition.role_env } else { '' }
    $role = if ($configuredRole) { $configuredRole } else { $definition.default_role }
    if (-not $username -or $username.StartsWith('change_me_') -or -not $password -or $password.StartsWith('CHANGE_ME_')) {
        throw "$($definition.username_env) and $($definition.password_env) must be set in the external deployment env file"
    }
    if ($role -notin $allowedRoles) {
        throw "$($definition.role_env) must contain a supported authentication role"
    }
    if ($username -notmatch '^[a-z0-9._-]{3,64}$' -or $password.Length -lt 12) {
        throw "$role login must use a valid username and a password of at least 12 characters"
    }
    # Role 회전은 같은 사람의 저장 Analysis·Report 소유권을 끊지 않아야 한다. username은
    # principal 파일에서 unique하므로 기존 subject를 Role과 무관하게 보존한다.
    $matching = @($existing | Where-Object { $_.username -eq $username }) | Select-Object -First 1
    $salt = [byte[]]::new(16)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($salt)
    $generator.Dispose()
    [ordered]@{
        username = $username
        password_salt = [Convert]::ToBase64String($salt).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        password_hash = Get-PasswordHash $password $salt $iterations
        password_iterations = $iterations
        subject = if ($matching) { $matching.subject } else { [guid]::NewGuid().ToString() }
        role = $role
        active = $true
    }
}

[IO.File]::WriteAllText($resolvedEnvPath, $envText, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText(
    $resolvedPrincipalPath,
    (ConvertTo-Json @($principals) -Depth 5) + "`r`n",
    [Text.UTF8Encoding]::new($false)
)

[ordered]@{
    status = 'PROVISIONED'
    principal_count = @($principals).Count
    roles = @($principals.role)
    password_storage = 'PBKDF2-SHA256'
} | ConvertTo-Json -Compress
