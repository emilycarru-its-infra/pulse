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
if ($names.product -and $names.product -notmatch '[\\/:.]') {
    Remove-TreeSafely (Join-Path $env:ProgramData $names.product) $env:ProgramData
}
Write-Host "Removed $($names.product)."
