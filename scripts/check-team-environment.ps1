[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Write-Pass([string]$Message) {
    Write-Output "PASS  $Message"
}

function Add-Failure([string]$Message) {
    $failures.Add($Message)
    Write-Output "FAIL  $Message"
}

function Add-Warning([string]$Message) {
    $warnings.Add($Message)
    Write-Output "WARN  $Message"
}

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw "Run this script inside the project Git repository."
}

Push-Location $repoRoot
try {
    & git --version
    if ($LASTEXITCODE -eq 0) { Write-Pass "Git is available." } else { Add-Failure "Git is unavailable." }

    $pythonOk = $false
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python --version
        $pythonOk = $LASTEXITCODE -eq 0
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 --version
        $pythonOk = $LASTEXITCODE -eq 0
    }
    if ($pythonOk) { Write-Pass "Python 3 is available." } else { Add-Failure "Python 3 is required." }

    $name = (& git config --local --get user.name 2>$null)
    $email = (& git config --local --get user.email 2>$null)
    if ($name) { Write-Pass "Local Git user.name is set: $name" } else { Add-Failure "Local Git user.name is missing." }
    if ($email) { Write-Pass "Local Git user.email is set: $email" } else { Add-Failure "Local Git user.email is missing." }

    $hooksPath = (& git config --local --get core.hooksPath 2>$null)
    if ($hooksPath -eq ".githooks") {
        Write-Pass "core.hooksPath=.githooks"
    }
    else {
        Add-Failure "Git hooks are not installed. Run scripts/setup-repo.ps1."
    }

    $source = Join-Path $repoRoot "docs\engineering\CODEX_GLOBAL_AGENTS.md"
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $target = Join-Path $codexHome "AGENTS.md"
    $override = Join-Path $codexHome "AGENTS.override.md"
    if (-not (Test-Path -LiteralPath $target)) {
        Add-Failure "Personal Codex AGENTS.md is missing. Run install-global-codex-agents.ps1."
    }
    elseif ((Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash -ne (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash) {
        Add-Failure "Personal Codex AGENTS.md differs from the team canonical file."
    }
    else {
        Write-Pass "Personal Codex AGENTS.md is synchronized."
    }
    if (Test-Path -LiteralPath $override) {
        Add-Warning "AGENTS.override.md exists and takes precedence over AGENTS.md."
    }

    $probes = @(
        ".agents/skills/draft-commit-message/SKILL.md",
        ".claude/skills/draft-commit-message/SKILL.md",
        "docs/engineering/TEAM_DEVELOPMENT_SETUP_GUIDE.md",
        "evals/testsets/.gitkeep"
    )
    foreach ($probe in $probes) {
        & git check-ignore --no-index --quiet $probe
        if ($LASTEXITCODE -eq 0) {
            Add-Failure "Shared path is ignored: $probe"
        }
        else {
            Write-Pass "Shared path is versionable: $probe"
        }
    }

    $hasHead = $false
    try {
        & git rev-parse --verify HEAD 2>$null | Out-Null
        $hasHead = $LASTEXITCODE -eq 0
    }
    catch {
        $hasHead = $false
    }
    if ($hasHead) {
        $branch = (& git branch --show-current)
        if ($branch) {
            if ($pythonOk) {
                if (Get-Command python -ErrorAction SilentlyContinue) {
                    & python scripts/validate_branch_name.py --branch $branch
                }
                else {
                    & py -3 scripts/validate_branch_name.py --branch $branch
                }
                if ($LASTEXITCODE -eq 0) { Write-Pass "Branch name is valid: $branch" } else { Add-Failure "Branch name is invalid: $branch" }
            }
        }
    }
    else {
        Add-Warning "No initial commit exists yet; branch checks were skipped."
    }

    if ($pythonOk) {
        if (Get-Command python -ErrorAction SilentlyContinue) {
            & python scripts/validate_collaboration_setup.py
        }
        else {
            & py -3 scripts/validate_collaboration_setup.py
        }
        if ($LASTEXITCODE -eq 0) { Write-Pass "Collaboration assets passed validation." } else { Add-Failure "Collaboration asset validation failed." }
    }

    Write-Output ""
    Write-Output "Summary: $($failures.Count) failure(s), $($warnings.Count) warning(s)"
    if ($failures.Count -gt 0) {
        exit 1
    }
}
finally {
    Pop-Location
}
