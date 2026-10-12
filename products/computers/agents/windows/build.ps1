<#
.SYNOPSIS
    Builds the Windows agent: the command-line agent, the per-user idle helper and the GUI, published
    together into publish\<arch>\ for each architecture with names.json and the install scripts,
    ready to be signed and packaged.

.DESCRIPTION
    Code signing and packaging happen downstream, in the deploying organization's pipeline; this
    script only builds. The names of the executables come from Directory.Build.props.

.PARAMETER Architecture
    x64, arm64 or both (default).

.PARAMETER Test
    Run the unit tests first.
#>
param(
    [ValidateSet('x64', 'arm64', 'both')]
    [string]$Architecture = 'both',
    [switch]$Test
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

$stamp = Get-Date -Format 'yyyy.MM.dd.HHmm'

# The product's names, from Directory.Build.props, for the install scripts.
$props = ([xml](Get-Content (Join-Path $PSScriptRoot 'Directory.Build.props') -Raw)).Project.PropertyGroup | Select-Object -First 1
$names = [ordered]@{ product = $props.PulseProductKey; gui = $props.PulseGuiName; cli = $props.PulseCliName; idle = $props.PulseIdleName; version = $stamp }
$arches = if ($Architecture -eq 'both') { @('x64', 'arm64') } else { @($Architecture) }

function Invoke-Dotnet {
    & dotnet @args
    if ($LASTEXITCODE -ne 0) { throw "dotnet $($args -join ' ') failed with exit code $LASTEXITCODE" }
}

if ($Test) {
    Invoke-Dotnet test tests\PulseAgent.Core.Tests --configuration Release --verbosity minimal
}

# Generates resources.pri for the GUI. The project sets EnableCoreMrtTooling=false because the MSBuild
# PRI step needs the Visual Studio UWP workload; this does the same with makepri.exe from the
# Windows SDK: it copies the compiled XAML (XBF) next to the executable and merges it with the
# WinUI framework PRIs into one resources.pri.
function Publish-AppResources([string]$Arch, [string]$OutputDir, [string]$ProjectDir) {
    $hostArch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
    $makepri = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\$hostArch\makepri.exe", "$env:ProgramFiles\Windows Kits\10\bin\*\$hostArch\makepri.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $makepri) { throw 'makepri.exe was not found; install the Windows 10/11 SDK.' }

    $xbf = Get-ChildItem "$ProjectDir\obj\Release" -Recurse -Filter *.xbf | Where-Object { $_.FullName -match [regex]::Escape("\win-$Arch\") }
    if (-not $xbf) { throw "No compiled XAML found for win-$Arch." }
    $root = ($xbf[0].FullName -split [regex]::Escape("\win-$Arch\"))[0] + "\win-$Arch"

    $staging = Join-Path ([IO.Path]::GetTempPath()) "pulseagent-pri-$Arch"
    Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory $staging | Out-Null
    foreach ($file in $xbf) {
        $relative = $file.FullName.Substring($root.Length).TrimStart('\')
        foreach ($target in @((Join-Path $staging $relative), (Join-Path $OutputDir $relative))) {
            New-Item -ItemType Directory (Split-Path $target) -Force | Out-Null
            Copy-Item $file.FullName $target -Force
        }
    }
    Get-ChildItem $OutputDir -Filter 'Microsoft.*.pri' | ForEach-Object { Copy-Item $_.FullName (Join-Path $staging $_.Name) }

    $config = Join-Path $staging 'priconfig.xml'
    & $makepri.FullName createconfig /cf $config /dq en-US /pv 10.0.0 /o | Out-Null
    $output = & $makepri.FullName new /pr $staging /cf $config /in PulseAgent /of (Join-Path $OutputDir 'resources.pri') /o 2>&1
    if ($LASTEXITCODE -ne 0) { throw "makepri failed: $output" }
    Remove-Item $staging -Recurse -Force
}

foreach ($arch in $arches) {
    $out = Join-Path $PSScriptRoot "publish\$arch"
    Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
    $common = @('--configuration', 'Release', '--runtime', "win-$arch", '--self-contained', 'true',
        '--output', $out, '--verbosity', 'minimal', "-p:BuildTimestamp=$stamp")

    Write-Host "Publishing $arch to $out"
    Invoke-Dotnet publish src\PulseAgent.Cli @common
    Invoke-Dotnet publish src\PulseAgent.Idle @common
    Invoke-Dotnet publish src\PulseAgent.App @common
    Publish-AppResources -Arch $arch -OutputDir $out -ProjectDir (Join-Path $PSScriptRoot 'src\PulseAgent.App')
    $names | ConvertTo-Json | Set-Content (Join-Path $out 'names.json') -Encoding UTF8
    Copy-Item packaging\install.ps1, packaging\uninstall.ps1, packaging\safety.ps1 $out

    Get-ChildItem $out -Filter *.exe | Where-Object Name -ne 'createdump.exe' | ForEach-Object { Write-Host "  $($_.Name)" }
}
Write-Host "Built $stamp"
