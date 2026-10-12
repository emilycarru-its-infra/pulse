<#
.SYNOPSIS
    Removes the agent: its scheduled tasks, its running processes and its install folder,
    Program Files\<product>. The logs under ProgramData stay; status.json is deleted by full path.
#>
$ErrorActionPreference = 'Continue'
$names = Get-Content (Join-Path $PSScriptRoot 'names.json') -Raw | ConvertFrom-Json
if ($names.product -notmatch '^[A-Za-z0-9]+$') { throw 'Unexpected product name in names.json' }

foreach ($task in $names.product, "$($names.product) Idle", "$($names.product) Shutdown") {
    Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
}
Get-Process -Name $names.cli, $names.idle, $names.gui -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$logs = Join-Path (Join-Path $env:ProgramData $names.product) 'logs'
foreach ($name in 'status.json', 'status.json.tmp') {
    $file = Join-Path $logs $name
    if (Test-Path -LiteralPath $file -PathType Leaf) { [IO.File]::Delete($file) }
}

# rmdir removes a junction inside the folder without following it, where Remove-Item -Recurse
# in Windows PowerShell would delete the junction's target.
$install = Join-Path $env:ProgramFiles $names.product
if (Test-Path -LiteralPath $install) { cmd.exe /d /c rmdir /s /q "`"$install`"" }
Write-Host "Removed $($names.product); its logs are kept in $logs."
