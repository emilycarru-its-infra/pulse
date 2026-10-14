# ComputerPulse uninstall
#
# Runs when the MSI is removed. Windows Installer has already deleted the installed files by the
# time this runs, including the agent's own uninstall.ps1, so this does the same work itself:
# stops and removes the three scheduled tasks, stops the agent, the idle helper and the app,
# deletes status.json by full path, removes the install folder and the Start Menu shortcut.
# The logs under C:\ProgramData\ManagedPresence\logs stay. Best effort; never fails the removal.
$ErrorActionPreference = 'Continue'

foreach ($task in 'ComputerPulse', 'ComputerPulse Idle', 'ComputerPulse Shutdown') {
    Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
}
foreach ($name in 'managedpresencebeacon', 'managedpresencebeacon-idle', 'Managed Presence Beacon') {
    Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

$logs = 'C:\ProgramData\ManagedPresence\logs'
foreach ($name in 'status.json', 'status.json.tmp') {
    $file = Join-Path $logs $name
    if (Test-Path -LiteralPath $file -PathType Leaf) { [IO.File]::Delete($file) }
}

# A file the agent still held when Windows Installer ran is only marked for deletion at restart,
# which leaves the folder behind. rmdir removes a junction inside it without following it, where
# Remove-Item -Recurse in Windows PowerShell would delete the junction's target.
$install = 'C:\Program Files\ComputerPulse'
if (Test-Path -LiteralPath $install) { cmd.exe /d /c rmdir /s /q "`"$install`"" }

$shortcut = 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Managed Presence Beacon.lnk'
if (Test-Path -LiteralPath $shortcut -PathType Leaf) { Remove-Item -LiteralPath $shortcut -Force }

exit 0
