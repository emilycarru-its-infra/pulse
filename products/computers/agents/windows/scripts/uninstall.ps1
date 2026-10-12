# ComputerPulse uninstall
#
# Runs the agent's uninstall.ps1, which removes the three scheduled tasks and the install folder
# and deletes status.json by full path; the logs under C:\ProgramData\ManagedPresence\logs stay.
# Then removes the Start Menu shortcut.
$ErrorActionPreference = 'Continue'

$script = Join-Path 'C:\Program Files\ComputerPulse' 'uninstall.ps1'
if (Test-Path -LiteralPath $script) { & $script }

$shortcut = 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Managed Presence Beacon.lnk'
if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut -Force }

exit 0
