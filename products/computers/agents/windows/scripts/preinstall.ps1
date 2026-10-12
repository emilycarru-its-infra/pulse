# ComputerPulse preinstall
#
# Stops the agent and the idle helper so the install can replace their files. The agent's own
# install.ps1, run by postinstall, registers and starts everything again. Idempotent; MSI custom
# actions run under Windows PowerShell 5.1.
$ErrorActionPreference = 'Continue'

foreach ($task in 'ComputerPulse', 'ComputerPulse Idle') {
    Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
}
foreach ($name in 'managedpulse', 'managedpulse-idle', 'Managed Presence Beacon') {
    Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

exit 0
