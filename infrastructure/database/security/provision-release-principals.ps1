# 책임: Git에서 제외된 repository `.env`의 analyst/admin bootstrap 자격증명을
# PBKDF2 verifier로 변환해 App PostgreSQL의 권위 계정 저장소에 명시적으로 반영한다.
[CmdletBinding()]
param(
    [string]$EnvPath,
    [string]$LegacyPrincipalPath,
    [string]$AnalystUsername,
    [string]$AdminUsername,
    [int]$SessionTtlSeconds = 0,
    [switch]$PromptAnalystPassword,
    [switch]$PromptAdminPassword
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot '..\..\..'))
. (Join-Path $scriptRoot '../scripts/deployment-environment.ps1')
$resolvedEnvPath = Resolve-RepositoryDeploymentEnvFile `
    -Path $EnvPath -RepositoryRoot $repoRoot
$envText = [IO.File]::ReadAllText($resolvedEnvPath)

# dotenv key는 설정 문법으로만 읽는다. 비밀번호 값은 출력·argv·log에 전달하지 않는다.
function Read-EnvValue([string]$Name) {
    $match = [regex]::Match($script:envText, "(?m)^$([regex]::Escape($Name))=(.*)$")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return ''
}

# 동일 key의 모든 기존 entry를 같은 opaque value로 정규화한다. MatchEvaluator를
# 사용하므로 password 안의 '$'도 replacement group으로 재해석되지 않는다.
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

# 폐기된 사람 Role 선택·별도 관리자 key는 새 bootstrap 성공 여부와 관계없이 다시
# credential source가 되지 않게 최종 `.env`에서 제거한다.
function Remove-EnvValue([string]$Name) {
    $pattern = "(?m)^$([regex]::Escape($Name))=.*(?:\r?\n|$)"
    $script:envText = [regex]::Replace($script:envText, $pattern, '')
}

# session secret은 CSPRNG 결과를 dotenv에 안전한 URL-safe base64 문자열로 바꾼다.
# padding은 session secret 표현에 포함하지 않는다.
function New-RandomValue([int]$ByteCount = 32) {
    $bytes = [byte[]]::new($ByteCount)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# 일반 command parameter로 password를 받지 않는다. secure prompt의 원문은 repository
# `.env`를 갱신하는 동안에만 메모리에 두고 즉시 해제한다.
function Set-PromptedPassword([string]$Name, [string]$Prompt, [string]$Label) {
    $securePassword = Read-Host $Prompt -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        if ($plainPassword.Length -lt 12) {
            throw "$Label password must contain at least 12 characters."
        }
        Set-EnvValue $Name $plainPassword
    } finally {
        if ($passwordPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        }
        $plainPassword = $null
        $securePassword = $null
    }
}

if ($AnalystUsername) {
    Set-EnvValue 'ANALYST_LOGIN_ID' $AnalystUsername.Trim().ToLowerInvariant()
}
if ($AdminUsername) {
    Set-EnvValue 'ADMIN_LOGIN_ID' $AdminUsername.Trim().ToLowerInvariant()
}
if ($SessionTtlSeconds) {
    if ($SessionTtlSeconds -lt 900 -or $SessionTtlSeconds -gt 86400) {
        throw 'SessionTtlSeconds must be between 900 and 86400.'
    }
    Set-EnvValue 'AUTH_SESSION_TTL_SECONDS' ([string]$SessionTtlSeconds)
}
if ($PromptAnalystPassword) {
    Set-PromptedPassword 'ANALYST_LOGIN_PASSWORD' 'Analyst password' 'Analyst'
}
if ($PromptAdminPassword) {
    Set-PromptedPassword 'ADMIN_LOGIN_PASSWORD' 'Admin password' 'Admin'
}

$sessionSecret = Read-EnvValue 'AUTH_SESSION_SECRET'
if (-not $sessionSecret -or $sessionSecret.StartsWith('CHANGE_ME_')) {
    Set-EnvValue 'AUTH_SESSION_SECRET' (New-RandomValue)
}
$legacyPrincipalSetting = Read-EnvValue 'AUTH_PRINCIPALS_HOST_FILE'
if (-not [string]::IsNullOrWhiteSpace($legacyPrincipalSetting) -and
    [string]::IsNullOrWhiteSpace($LegacyPrincipalPath)) {
    throw 'Legacy principal migration is pending; pass the verified absolute path with -LegacyPrincipalPath.'
}
Remove-EnvValue 'ANALYST_LOGIN_ROLE'
Remove-EnvValue 'REPORT_ADMIN_LOGIN_ID'
Remove-EnvValue 'REPORT_ADMIN_LOGIN_PASSWORD'

# 사람 bootstrap Role은 설정으로 선택하지 않는다. 두 고정 정의 외의 과거 Role이나
# 추가 운영자 계정은 이 경계를 통해 만들 수 없다.
$definitions = @(
    [ordered]@{
        username_env = 'ANALYST_LOGIN_ID'
        password_env = 'ANALYST_LOGIN_PASSWORD'
        role = 'analyst'
    },
    [ordered]@{
        username_env = 'ADMIN_LOGIN_ID'
        password_env = 'ADMIN_LOGIN_PASSWORD'
        role = 'admin'
    }
)
# 최초 JSON→DB 전환에서 기존 subject를 가져올 수 있는 one-time 입력이다. runtime은 이
# 파일을 읽지 않으며 명시하지 않은 경로를 자동 탐색하지 않는다.
function Read-LegacySubjects([AllowEmptyString()] [string]$Path) {
    $subjects = [Collections.Generic.Dictionary[string, string]]::new(
        [StringComparer]::Ordinal
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { return $subjects }
    if (-not (Test-FullyQualifiedFileSystemPath $Path) -or
        -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'LegacyPrincipalPath must be an existing absolute file.'
    }
    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    $item = Get-Item -LiteralPath $resolved -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'LegacyPrincipalPath must not be a symbolic link or reparse point.'
    }
    if ($item.Length -gt 1MB) {
        throw 'LegacyPrincipalPath must not exceed 1 MiB.'
    }
    $repositoryPrefix = $repoRoot.TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    ) + [IO.Path]::DirectorySeparatorChar
    if ($resolved.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        & git -C $repoRoot check-ignore -q -- $resolved
        if ($LASTEXITCODE -ne 0) {
            throw 'Repository-local LegacyPrincipalPath must be covered by .gitignore.'
        }
    }
    try { $document = [IO.File]::ReadAllText($resolved) | ConvertFrom-Json }
    catch { throw 'LegacyPrincipalPath must contain a valid principal JSON array.' }
    if ($document -isnot [array]) {
        throw 'LegacyPrincipalPath must contain a principal JSON array.'
    }
    $records = @($document)
    $observedSubjects = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($record in $records) {
        $username = if ($null -ne $record.username) {
            ([string]$record.username).Trim().ToLowerInvariant()
        } else { '' }
        $subject = if ($null -ne $record.subject) { [string]$record.subject } else { '' }
        $parsedSubject = [guid]::Empty
        if ($username -notmatch '^[a-z0-9._-]{3,64}$' -or
            -not [guid]::TryParse($subject, [ref]$parsedSubject) -or
            $subjects.ContainsKey($username) -or
            -not $observedSubjects.Add($parsedSubject.ToString())) {
            throw 'LegacyPrincipalPath contains an invalid or duplicate username/subject.'
        }
        $subjects[$username] = $parsedSubject.ToString()
    }
    $observedSubjects = $null
    $document = $null
    return $subjects
}

$legacySubjects = Read-LegacySubjects $LegacyPrincipalPath
$bootstrapAccounts = foreach ($definition in $definitions) {
    $username = (Read-EnvValue $definition.username_env).Trim().ToLowerInvariant()
    $password = Read-EnvValue $definition.password_env
    if (-not $username -or $username.StartsWith('change_me_') -or
        -not $password -or $password.StartsWith('CHANGE_ME_')) {
        throw "$($definition.username_env) and $($definition.password_env) must be set in infrastructure/database/.env"
    }
    if ($username -notmatch '^[a-z0-9._-]{3,64}$' -or $password.Length -lt 12) {
        throw "$($definition.role) login must use a valid username and a password of at least 12 characters"
    }
    [ordered]@{
        subject = if ($legacySubjects.ContainsKey($username)) {
            $legacySubjects[$username]
        } else {
            [guid]::NewGuid().ToString()
        }
        username = $username
        password = $password
        role = $definition.role
    }
}
if ([string]$bootstrapAccounts[0]['username'] -eq
    [string]$bootstrapAccounts[1]['username']) {
    throw 'ANALYST_LOGIN_ID and ADMIN_LOGIN_ID must be different usernames.'
}
if ($LegacyPrincipalPath -and
    @($bootstrapAccounts | Where-Object { -not $legacySubjects.ContainsKey($_.username) }).Count -gt 0) {
    throw 'LegacyPrincipalPath must contain both configured bootstrap usernames.'
}

# DB 반영 실패 뒤에도 같은 credential로 안전하게 재시도할 수 있도록 prompt 변경을 먼저
# repository `.env`에 고정한다. `.env` 변경만으로 DB account가 바뀌지는 않는다.
[IO.File]::WriteAllText($resolvedEnvPath, $envText, [Text.UTF8Encoding]::new($false))

$deploymentValues = Read-DeploymentEnvironment $resolvedEnvPath
Assert-DeploymentEnvironmentValues -Values $deploymentValues -RequiredKeys @(
    'APP_DB_NAME', 'APP_MIGRATION_USER', 'APP_MIGRATION_PASSWORD'
)
$databaseUrl = 'postgresql+psycopg://{0}:{1}@app-postgres:5432/{2}' -f @(
    [Uri]::EscapeDataString([string]$deploymentValues['APP_MIGRATION_USER'])
    [Uri]::EscapeDataString([string]$deploymentValues['APP_MIGRATION_PASSWORD'])
    [Uri]::EscapeDataString([string]$deploymentValues['APP_DB_NAME'])
)
$requestJson = ConvertTo-Json ([ordered]@{
    database_url = $databaseUrl
    require_subject_match = -not [string]::IsNullOrWhiteSpace($LegacyPrincipalPath)
    accounts = @($bootstrapAccounts)
}) -Depth 4 -Compress
$composeFile = Join-Path $repoRoot 'compose.yml'
$composeEnvArguments = @(Get-ComposeEnvironmentArguments $resolvedEnvPath)
Disable-ImplicitComposeEnvironment

try {
    $output = @($requestJson | & docker compose @composeEnvArguments `
        --file $composeFile --profile dev run --rm --build --no-deps -T `
        --entrypoint python app-migrations scripts/provision_accounts.py)
    if ($LASTEXITCODE -ne 0) {
        throw 'Account provisioning failed; ensure app-postgres is running and the current migration is applied.'
    }
    $result = $output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -Last 1 | ConvertFrom-Json
    if ($result.status -ne 'ok' -or [int]$result.processed -ne 2) {
        throw 'Account provisioning returned an invalid result.'
    }
    # 기존 subject 보존이 DB에 성공한 뒤에만 runtime principal 경로 key를 폐기한다.
    # 실패 시 key를 남겨 다음 실행도 explicit legacy 이관 없이는 fail closed한다.
    Remove-EnvValue 'AUTH_PRINCIPALS_HOST_FILE'
    [IO.File]::WriteAllText(
        $resolvedEnvPath,
        $envText,
        [Text.UTF8Encoding]::new($false)
    )
} finally {
    $requestJson = $null
    $databaseUrl = $null
    $deploymentValues = $null
    $output = $null
    $result = $null
    $envText = $null
    $sessionSecret = $null
    $legacyPrincipalSetting = $null
    $legacySubjects = $null
    $bootstrapAccounts = $null
}

[ordered]@{
    status = 'PROVISIONED'
    account_count = 2
    roles = @('analyst', 'admin')
    authoritative_store = 'APP_POSTGRES_SECURITY_ACCOUNTS'
    password_storage = 'BACKEND_CREATE_PASSWORD_VERIFIER'
    sessions = 'REVOKED'
} | ConvertTo-Json -Compress
