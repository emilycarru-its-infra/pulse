# ComputerPulse postinstall
#
# Runs the agent's own install.ps1 from the install folder. It creates C:\ProgramData\ManagedPulse
# with a protected ACL (and stops if a link or a folder a user owns is already there), registers
# the \ComputerPulse (SYSTEM, from boot), \ComputerPulse Idle (each user's session) and
# \ComputerPulse Shutdown (event 1074) tasks, and starts the agent. It refuses to run from anywhere
# but C:\Program Files\ComputerPulse.
#
# Settings are not set here: the ingest address comes from policy under
# HKLM\SOFTWARE\Policies\ComputerPulse, and the agent sends nothing until it has one.
# Also adds a Start Menu shortcut for Managed Presence Beacon. Idempotent; Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'

$InstallDir = 'C:\Program Files\ComputerPulse'
& (Join-Path $InstallDir 'install.ps1')

try {
    $gui = Join-Path $InstallDir 'Managed Presence Beacon.exe'
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut('C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Managed Presence Beacon.lnk')
    $shortcut.TargetPath = $gui
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = 'What this computer reports to the Computers status page'
    $shortcut.IconLocation = "$gui,0"
    $shortcut.Save()
} catch {
    Write-Warning "Start Menu shortcut not created: $_"
}

exit 0
