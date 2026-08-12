[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$BackupDirectory,
    [Parameter(Mandatory)][string]$EncryptionKeyFile,
    [Parameter(Mandatory)][string]$EvidenceDirectory,
    [datetime]$At = '02:00',
    [string]$TaskName = 'Answervice-AppPostgres-Daily-Maintenance'
)

$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'run-app-postgres-maintenance.ps1'
$keyPath = [System.IO.Path]::GetFullPath($EncryptionKeyFile)
if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw 'External encryption key file is required.' }

$paths = @(
    [System.IO.Path]::GetFullPath($BackupDirectory),
    $keyPath,
    [System.IO.Path]::GetFullPath($EvidenceDirectory),
    [System.IO.Path]::GetFullPath($runner)
)
if ($paths.Where({ $_.Contains('"') }).Count) { throw 'Paths containing double quotes are not supported.' }

$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -BackupDirectory "{1}" -EncryptionKeyFile "{2}" -EvidenceDirectory "{3}"' -f `
    $paths[3], $paths[0], $paths[1], $paths[2]
$action = New-ScheduledTaskAction -Execute (Get-Process -Id $PID).Path -Argument $arguments -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew

if ($PSCmdlet.ShouldProcess($TaskName, 'Register daily encrypted backup and dry-run retention task')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Answervice encrypted app-postgres backup followed by retention dry-run.' -Force | Out-Null
    "APP_POSTGRES_MAINTENANCE_TASK_INSTALLED $TaskName"
}
