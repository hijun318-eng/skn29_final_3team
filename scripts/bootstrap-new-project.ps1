[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath,

    [string]$GitUserName,

    [string]$GitUserEmail
)

$ErrorActionPreference = "Stop"

$sourceRoot = (& git -C (Join-Path $PSScriptRoot "..") rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $sourceRoot) {
    $sourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

$sourceFull = [System.IO.Path]::GetFullPath($sourceRoot).TrimEnd('\')
$targetFull = [System.IO.Path]::GetFullPath($TargetPath).TrimEnd('\')

if ($targetFull -eq $sourceFull -or $targetFull.StartsWith("$sourceFull\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "TargetPath must be outside the collaboration template repository: $sourceFull"
}

if (Test-Path -LiteralPath $targetFull) {
    $existing = @(Get-ChildItem -LiteralPath $targetFull -Force)
    if ($existing.Count -gt 0) {
        throw "TargetPath must be empty: $targetFull"
    }
}
else {
    New-Item -ItemType Directory -Path $targetFull -Force | Out-Null
}

$manifest = @(
    ".agents",
    ".claude",
    ".github",
    ".githooks",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".env.example",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "requirements.txt",
    "data",
    "docs\engineering",
    "evals",
    "notebooks",
    "src",
    "app",
    "submission",
    "tests",
    "scripts"
)

foreach ($item in $manifest) {
    $source = Join-Path $sourceFull $item
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Bootstrap source is missing: $source"
    }

    $destination = Join-Path $targetFull $item
    $parent = Split-Path -Parent $destination
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
}

Copy-Item -LiteralPath (Join-Path $sourceFull "docs\engineering\templates\PROJECT_README.md") `
    -Destination (Join-Path $targetFull "README.md") -Force

& git init -b main $targetFull
if ($LASTEXITCODE -ne 0) {
    throw "Failed to initialize the new Git repository."
}

Push-Location $targetFull
try {
    & git config --local core.hooksPath .githooks
    if ($GitUserName) {
        & git config --local user.name $GitUserName
    }
    if ($GitUserEmail) {
        & git config --local user.email $GitUserEmail
    }

    & powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-repo.ps1 -CheckOnly
    if ($LASTEXITCODE -ne 0) {
        throw "The copied collaboration environment did not pass validation."
    }
}
finally {
    Pop-Location
}

Write-Output "New project collaboration environment created: $targetFull"
Write-Output "No files were staged or committed. Review git status before the initial commit."
Write-Output "After the initial commit, run scripts/create-branch-structure.ps1."
