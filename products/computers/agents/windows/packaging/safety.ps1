# Path checks shared by install.ps1 and uninstall.ps1, which run as an administrator or SYSTEM and
# so must never follow a link a user planted or trust a folder a user created.

$script:TrustedOwners = @('S-1-5-18', 'S-1-5-32-544')   # SYSTEM, Administrators
$script:UserSids = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545', 'S-1-5-4')   # Everyone, Authenticated Users, Users, INTERACTIVE

function Test-ReparsePoint([System.IO.FileSystemInfo]$Item) {
    ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
}

function Get-OwnerSid([string]$Path) {
    (Get-Acl -LiteralPath $Path).GetOwner([Security.Principal.SecurityIdentifier]).Value
}

# Deletes a tree without following links: a junction or symbolic link is removed itself, never
# its target, and nothing outside $Root is touched.
function Remove-TreeSafely([string]$Path, [string]$Root) {
    $full = [IO.Path]::GetFullPath($Path)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $full.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing to delete $full outside $rootFull" }
    $item = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
    if (-not $item) { return }
    if (Test-ReparsePoint $item) {
        if ($item.PSIsContainer) { [IO.Directory]::Delete($full, $false) } else { [IO.File]::Delete($full) }
        return
    }
    if ($item.PSIsContainer) {
        foreach ($child in Get-ChildItem -LiteralPath $full -Force) { Remove-TreeSafely $child.FullName $Root }
        [IO.Directory]::Delete($full, $false)
    } else {
        [IO.File]::Delete($full)
    }
}

# Creates a folder, or takes over an existing one, so that only SYSTEM and Administrators can
# write to it. A folder that is a link, or that someone other than SYSTEM or Administrators owns,
# is deleted (without following links) and made again; leftovers inside that are links or owned
# by anyone else are deleted.
function New-SecureDirectory([string]$Path, [string]$Root, [string[]]$Grants) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($item -and ((Test-ReparsePoint $item) -or -not $item.PSIsContainer -or ($script:TrustedOwners -notcontains (Get-OwnerSid $Path)))) {
        Remove-TreeSafely $Path $Root
        $item = $null
    }
    if (-not $item) { [IO.Directory]::CreateDirectory($Path) | Out-Null }
    icacls $Path /setowner '*S-1-5-32-544' | Out-Null
    icacls $Path /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' @Grants | Out-Null
    foreach ($child in Get-ChildItem -LiteralPath $Path -Force) {
        if ((Test-ReparsePoint $child) -or ($script:TrustedOwners -notcontains (Get-OwnerSid $child.FullName))) {
            Remove-TreeSafely $child.FullName $Path
        }
    }
}

# True when a user who is not an administrator could change files in $Path.
function Test-UserWritable([string]$Path) {
    # WriteData/CreateFiles, AppendData/CreateDirectories, WriteExtendedAttributes, WriteAttributes,
    # Delete, ChangePermissions, TakeOwnership, GENERIC_WRITE and GENERIC_ALL. Read bits do not count.
    $write = 0x2 -bor 0x4 -bor 0x10 -bor 0x100 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x40000000 -bor 0x10000000
    foreach ($rule in (Get-Acl -LiteralPath $Path).Access) {
        $sid = try { $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } catch { $null }
        if ($rule.AccessControlType -eq 'Allow' -and $script:UserSids -contains $sid -and ([int64]$rule.FileSystemRights -band $write)) { return $true }
    }
    $false
}
