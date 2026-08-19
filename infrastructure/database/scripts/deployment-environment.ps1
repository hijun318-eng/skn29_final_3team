# 책임: 운영 script가 repository-local `.env`를 묵시적으로 읽지 못하게 막고,
# 명시된 외부 env file 또는 현재 process environment만 Compose에 전달한다.

function Disable-ImplicitComposeEnvironment {
    <#
    Docker Compose의 현재 작업 directory 기반 `.env` 자동 탐색을 끈다.
    호출자가 명시한 `--env-file`은 계속 허용되며, 값이 없으면 process environment만
    사용하므로 ignored credential file이 우연히 운영 identity가 되지 않는다.
    #>
    $env:COMPOSE_DISABLE_ENV_FILE = '1'
}

function Test-FullyQualifiedFileSystemPath {
    <#
    Windows PowerShell 5.1과 PowerShell 7에서 동일하게 drive-rooted/UNC 또는 Unix
    root path만 허용한다. ``C:relative``처럼 현재 drive directory에 의존하는 값은
    .NET version과 무관하게 거절해 secret source가 실행 위치에 따라 바뀌지 않는다.
    #>
    param([AllowEmptyString()] [string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    if ([IO.Path]::DirectorySeparatorChar -eq '\') {
        return [bool]($Path -match '^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)')
    }
    return $Path.StartsWith('/', [StringComparison]::Ordinal)
}

function Resolve-ExternalDeploymentEnvFile {
    <#
    선택된 env file을 canonical absolute path로 해석하고 repository 밖인지 검증한다.
    빈 입력은 process environment 사용을 뜻하며, 상대 경로나 repository 내부 파일은
    caller의 현재 directory에 따라 credential source가 달라질 수 있어 거절한다.
    #>
    param(
        [AllowEmptyString()] [string]$Path,
        [Parameter(Mandatory)] [string]$RepositoryRoot
    )

    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    if (-not (Test-FullyQualifiedFileSystemPath $Path)) {
        throw 'EnvFilePath must be an absolute path outside the repository.'
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'EnvFilePath must reference an existing file.'
    }

    $resolvedPath = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    $resolvedRepository = [IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $RepositoryRoot).Path
    ).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $repositoryPrefix = $resolvedRepository + [IO.Path]::DirectorySeparatorChar
    if ($resolvedPath.Equals($resolvedRepository, [StringComparison]::OrdinalIgnoreCase) -or
        $resolvedPath.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'EnvFilePath must remain outside the repository.'
    }
    return $resolvedPath
}

function Get-ComposeEnvironmentArguments {
    <#
    검증된 env path만 Docker Compose CLI argument로 변환한다. path가 없으면 빈 배열을
    반환해 process environment를 사용하며, implicit `.env` 차단은 별도 함수가 맡는다.
    #>
    param([AllowNull()] [string]$ResolvedEnvFile)

    if ($ResolvedEnvFile) { return @('--env-file', $ResolvedEnvFile) }
    return @()
}

function Read-DeploymentEnvironment {
    <#
    외부 dotenv 또는 process environment를 key/value map으로 읽는다. dotenv의 중복
    key와 해석할 수 없는 행은 Compose와 검증 code의 값 불일치를 막기 위해 거절하며,
    값 자체는 출력하거나 expression으로 재평가하지 않는다.
    #>
    param([AllowNull()] [string]$ResolvedEnvFile)

    $values = [Collections.Generic.Dictionary[string, string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    if (-not $ResolvedEnvFile) {
        foreach ($entry in [Environment]::GetEnvironmentVariables('Process').GetEnumerator()) {
            $values[[string]$entry.Key] = [string]$entry.Value
        }
        return $values
    }

    $lineNumber = 0
    foreach ($line in Get-Content -LiteralPath $ResolvedEnvFile -Encoding UTF8) {
        $lineNumber++
        if ($line -match '^\s*(?:#.*)?$') { continue }
        if ($line -notmatch '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            throw "EnvFilePath contains unsupported dotenv syntax at line $lineNumber."
        }
        $key = $Matches[1]
        if ($values.ContainsKey($key)) {
            throw "EnvFilePath contains duplicate key '$key'."
        }
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Assert-DeploymentEnvironmentValues {
    <#
    caller가 실제로 소비할 key가 존재하고 placeholder가 아닌지 확인한다. secret 값은
    오류에 포함하지 않으며, 누락/placeholder를 Compose 실행 전에 차단한다.
    #>
    param(
        [Parameter(Mandatory)] $Values,
        [Parameter(Mandatory)] [string[]]$RequiredKeys
    )

    foreach ($key in $RequiredKeys) {
        $value = if ($Values.ContainsKey($key)) { [string]$Values[$key] } else { '' }
        if ([string]::IsNullOrWhiteSpace($value) -or
            $value.StartsWith('CHANGE_ME_', [StringComparison]::OrdinalIgnoreCase) -or
            $value.StartsWith('REQUIRED_', [StringComparison]::OrdinalIgnoreCase) -or
            $value -match '(?i)(^|[\\/])REQUIRED_') {
            throw "Deployment environment key '$key' is missing or still a placeholder."
        }
    }
}

function Assert-ExternalDeploymentFile {
    <#
    deployment map의 path key가 존재하는 외부 regular file을 가리키는지 확인한다.
    인증 DB·CA·keystore 같은 secret material이 repository 내부에 들어오거나 missing
    bind mount가 directory로 생성되는 상황을 Compose 호출 전에 차단한다.
    #>
    param(
        [Parameter(Mandatory)] $Values,
        [Parameter(Mandatory)] [string]$Key,
        [Parameter(Mandatory)] [string]$RepositoryRoot
    )

    Assert-DeploymentEnvironmentValues -Values $Values -RequiredKeys @($Key)
    $path = [string]$Values[$Key]
    if (-not (Test-FullyQualifiedFileSystemPath $path) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Deployment environment key '$Key' must reference an existing absolute file."
    }
    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $path).Path)
    $repository = [IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $RepositoryRoot).Path
    ).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    if ($resolved.StartsWith(
        $repository + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Deployment environment key '$Key' must reference a file outside the repository."
    }
    return $resolved
}
