<#
.SYNOPSIS
    Removes the agent's scheduled tasks and its data folder. The install folder is the package's to remove.
    The data folder is deleted without following links, and only when it sits directly in ProgramData.
#>
$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'safety.ps1')
$names = Get-Content (Join-Path $PSScriptRoot 'names.json') -Raw | ConvertFrom-Json
foreach ($task in $names.product, "$($names.product) Idle", "$($names.product) Shutdown") {
    Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
}
Get-Process -Name $names.cli, $names.idle -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
# Only the files the agent writes are deleted, by name, and then the folders if they are empty.
if ($names.product -match '^[A-Za-z0-9]+$') {
    $data = Join-Path $env:ProgramData $names.product
    Remove-KnownFiles (Join-Path $data 'idle') @('*.json', '*.json.tmp')
    Remove-KnownFiles (Join-Path $data 'logs') @("$($names.cli)-*.log")
    Remove-KnownFiles $data @('status.json', 'status.json.tmp')
    foreach ($dir in (Join-Path $data 'idle'), (Join-Path $data 'logs'), $data) { Remove-EmptyDirectory $dir }
}
Write-Host "Removed $($names.product)."
