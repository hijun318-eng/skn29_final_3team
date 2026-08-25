param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "ML 가상환경을 찾을 수 없습니다: $python"
}

if (-not $env:RAG_DATABASE_URL) {
    $container = docker inspect answervice-rag-pgvector | ConvertFrom-Json
    if (-not $container) {
        throw 'answervice-rag-pgvector 컨테이너를 찾을 수 없습니다.'
    }
    if ($container[0].State.Status -ne 'running') {
        docker start answervice-rag-pgvector | Out-Null
        $container = docker inspect answervice-rag-pgvector | ConvertFrom-Json
    }
    $settings = @{}
    foreach ($entry in $container[0].Config.Env) {
        $name, $value = $entry -split '=', 2
        $settings[$name] = $value
    }
    $dbPort = $container[0].NetworkSettings.Ports.'5432/tcp'[0].HostPort
    $user = [Uri]::EscapeDataString($settings.POSTGRES_USER)
    $password = [Uri]::EscapeDataString($settings.POSTGRES_PASSWORD)
    $database = [Uri]::EscapeDataString($settings.POSTGRES_DB)
    $env:RAG_DATABASE_URL = "postgresql://$user`:$password@127.0.0.1`:$dbPort/$database"
}

$env:PYTHONUTF8 = '1'
$arguments = @((Join-Path $PSScriptRoot 'local_console.py'), '--port', $Port)
if ($NoBrowser) { $arguments += '--no-browser' }
& $python @arguments
