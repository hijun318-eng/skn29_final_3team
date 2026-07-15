[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw "Run this script inside the Git repository."
}

$pythonMode = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonMode = "python"
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonMode = "py"
}
else {
    throw "Python 3 is required."
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    if ($pythonMode -eq "py") {
        & py -3 @Arguments
    }
    else {
        & python @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python validation failed: $($Arguments -join ' ')"
    }
}

Push-Location $repoRoot
try {
    Invoke-Python --version
    Invoke-Python scripts/validate_commit_message.py --message "chore(repo): verify commit message harness"
    Invoke-Python scripts/validate_branch_name.py --branch "junhee"
    Invoke-Python scripts/validate_pr_flow.py --head "junhee" --base "dev"
    Invoke-Python scripts/validate_collaboration_setup.py

    if (-not $CheckOnly) {
        & git config --local core.hooksPath .githooks
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to configure core.hooksPath."
        }
    }

    $hooksPath = (& git config --local --get core.hooksPath 2>$null)
    if ($CheckOnly -and $hooksPath -ne ".githooks") {
        Write-Warning "Git hooks are not installed. Run: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-repo.ps1"
    }

    Write-Output "Repository collaboration harness check passed."
    Write-Output "core.hooksPath=$hooksPath"
}
finally {
    Pop-Location
}
