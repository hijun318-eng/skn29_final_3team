# 책임: gitignored repository-local principal 저장소에 개발용 platform_admin을
# PBKDF2 verifier로 안전하게 upsert한다. 운영·외부 경로에는 사용할 수 없다.
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$PrincipalPath,
    [string]$Username = 'admin'
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot '..\..\..'))
. (Join-Path $scriptRoot '../scripts/deployment-environment.ps1')
$resolvedPrincipalPath = [IO.Path]::GetFullPath($PrincipalPath)
$principalParent = Split-Path -Parent $resolvedPrincipalPath
$repositoryPrefix = $repoRoot.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar

if (-not (Test-FullyQualifiedFileSystemPath $PrincipalPath) -or
    -not (Test-Path -LiteralPath $principalParent -PathType Container) -or
    -not $resolvedPrincipalPath.StartsWith(
        $repositoryPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'PrincipalPath must be an absolute repository-local path with an existing parent.'
}
& git -C $repoRoot check-ignore -q -- $resolvedPrincipalPath
if ($LASTEXITCODE -ne 0) {
    throw 'Repository-local PrincipalPath must be covered by .gitignore.'
}

$canonicalUsername = $Username.Trim().ToLowerInvariant()
if ($canonicalUsername -notmatch '^[a-z0-9._-]{3,64}$') {
    throw 'Username must contain 3-64 lowercase letters, digits, dot, underscore, or hyphen.'
}

function ConvertTo-Base64Url([byte[]]$Value) {
    return [Convert]::ToBase64String($Value).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-PasswordHash([string]$Password, [byte[]]$Salt, [int]$Iterations) {
    $derive = [Security.Cryptography.Rfc2898DeriveBytes]::new(
        $Password,
        $Salt,
        $Iterations,
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try {
        return ([BitConverter]::ToString($derive.GetBytes(32))).Replace('-', '').ToLowerInvariant()
    } finally {
        $derive.Dispose()
    }
}

$existing = @()
if (Test-Path -LiteralPath $resolvedPrincipalPath) {
    try {
        $existing = @((Get-Content -Raw -LiteralPath $resolvedPrincipalPath | ConvertFrom-Json))
    } catch {
        throw 'Existing principal file is not valid JSON.'
    }
}
if (@($existing | Group-Object username | Where-Object Count -gt 1).Count -gt 0) {
    throw 'Existing principal usernames must be unique.'
}

$securePassword = Read-Host 'Local platform admin password' -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    # 이 도구는 gitignored 로컬 개발 경로만 허용한다. 운영 release principal의
    # 12자 정책은 provision-release-principals.ps1에서 별도로 유지한다.
    if ($plainPassword.Length -lt 8) {
        throw 'Local development password must contain at least 8 characters.'
    }
    $iterations = 210000
    $salt = [byte[]]::new(16)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($salt) } finally { $generator.Dispose() }
    $matching = @($existing | Where-Object username -eq $canonicalUsername) |
        Select-Object -First 1
    $principal = [ordered]@{
        username = $canonicalUsername
        password_salt = ConvertTo-Base64Url $salt
        password_hash = Get-PasswordHash $plainPassword $salt $iterations
        password_iterations = $iterations
        subject = if ($matching) { $matching.subject } else { [guid]::NewGuid().ToString() }
        role = 'platform_admin'
        active = $true
    }
} finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    $plainPassword = $null
    $securePassword = $null
}

$principals = @($existing | Where-Object username -ne $canonicalUsername) + @($principal)
$payload = (ConvertTo-Json @($principals) -Depth 5) + "`r`n"
$temporaryPath = Join-Path $principalParent ('.principals-' + [guid]::NewGuid() + '.tmp')
try {
    [IO.File]::WriteAllText($temporaryPath, $payload, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryPath -Destination $resolvedPrincipalPath -Force
} finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}

[ordered]@{
    status = 'PROVISIONED'
    username = $canonicalUsername
    role = 'platform_admin'
    principal_count = @($principals).Count
    password_storage = 'PBKDF2-SHA256'
} | ConvertTo-Json -Compress
