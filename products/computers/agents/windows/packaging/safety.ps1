# Path rules shared by install.ps1 and uninstall.ps1, which run as an administrator or SYSTEM.
# They never act on a path a standard user could have created or swapped: a folder is used only
# when SYSTEM or Administrators own it and it is not a link, new folders are created with their
# final ACL in one call, and nothing is deleted recursively.

$script:TrustedOwners = @('S-1-5-18', 'S-1-5-32-544')   # SYSTEM, Administrators

function Test-TrustedDirectory([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item -or -not $item.PSIsContainer) { return $false }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
    $owner = $item.GetAccessControl().GetOwner([Security.Principal.SecurityIdentifier]).Value
    return $script:TrustedOwners -contains $owner
}

# A directory security descriptor owned by Administrators, inheriting nothing, giving SYSTEM and
# Administrators full control plus the extra rules given as @(sid, rights, inheritance, propagation).
function New-DirectorySecurity([object[]]$Extra = @()) {
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $security.SetOwner((New-Object Security.Principal.SecurityIdentifier 'S-1-5-32-544'))
    $security.SetAccessRuleProtection($true, $false)
    $rules = @(@('S-1-5-18', 'FullControl', 'ContainerInherit,ObjectInherit', 'None'),
               @('S-1-5-32-544', 'FullControl', 'ContainerInherit,ObjectInherit', 'None')) + $Extra
    foreach ($r in $rules) {
        $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            (New-Object Security.Principal.SecurityIdentifier $r[0]), $r[1], $r[2], $r[3], 'Allow')))
    }
    return $security
}

# Creates a directory with its final ACL in one call, or, when it already exists and is trusted,
# applies that ACL to it. An existing directory that is a link or that a standard user owns is
# left alone and the install stops: an administrator should look at it.
function Initialize-Directory([string]$Path, [object[]]$Extra = @()) {
    $security = New-DirectorySecurity $Extra
    if (-not (Test-Path -LiteralPath $Path)) {
        [IO.Directory]::CreateDirectory($Path, $security) | Out-Null
    } elseif (Test-TrustedDirectory $Path) {
        (Get-Item -LiteralPath $Path -Force).SetAccessControl($security)
    } else {
        throw "$Path exists but is a link or is owned by a standard user; remove it and install again."
    }
}

# Deletes the files with these exact names in a trusted directory, never following a link.
function Remove-KnownFiles([string]$Directory, [string[]]$Patterns) {
    if (-not (Test-TrustedDirectory $Directory)) { return }
    foreach ($pattern in $Patterns) {
        foreach ($file in Get-ChildItem -LiteralPath $Directory -Filter $pattern -File -Force -ErrorAction SilentlyContinue) {
            if (-not ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { [IO.File]::Delete($file.FullName) }
        }
    }
}

# Removes a directory only when it is trusted and already empty.
function Remove-EmptyDirectory([string]$Path) {
    if ((Test-TrustedDirectory $Path) -and -not (Get-ChildItem -LiteralPath $Path -Force)) { [IO.Directory]::Delete($Path, $false) }
}
