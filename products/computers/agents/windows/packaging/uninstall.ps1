<#
.SYNOPSIS
    Removes the agent's scheduled tasks and its data folder. The install folder is the package's to remove.
#>
$ErrorActionPreference = 'Continue'
$names = Get-Content (Join-Path $PSScriptRoot 'names.json') -Raw | ConvertFrom-Json
foreach ($task in $names.product, "$($names.product) Idle", "$($names.product) Shutdown") {
    Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
}
Get-Process -Name $names.cli, $names.idle -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $env:ProgramData $names.product) -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Removed $($names.product)."
