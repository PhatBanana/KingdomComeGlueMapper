# A private launch root, entirely inside Mods. Nothing is installed over retail.
# Run the ordinary Steam shortcut to use the original Engine shaders again.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ModDirectory, [switch]$PrepareOnly, [switch]$StartupCheck)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hash.Dispose() }
}

$mod = [IO.Path]::GetFullPath($ModDirectory).TrimEnd('\', '/')
$mods = [IO.Directory]::GetParent($mod).FullName
$game = [IO.Directory]::GetParent($mods).FullName
$identity = ([xml](Get-Content -LiteralPath (Join-Path $mod 'mod.manifest') -Raw)).kcd_mod.info.modid
if ($identity -notmatch '^[a-z0-9_]+$' -or [IO.Path]::GetFileName($mods) -ine 'Mods') {
    throw 'Install this package in the game Mods folder before using its shader launcher.'
}
if (Get-Process KingdomCome -ErrorAction SilentlyContinue) {
    throw 'Close Kingdom Come before preparing or launching the shader runtime.'
}
$shader = Join-Path $mod 'ShaderCache'
$report = Get-Content -LiteralPath (Join-Path $shader 'shader-build.json') -Raw | ConvertFrom-Json
$archives = @('Shaders.pak', 'ShadersBin.pak', 'ShaderCache.pak', 'ShaderCacheStartup.pak')
if (-not $report.compiled -or @($report.files.PSObject.Properties).Count -ne 4) {
    throw 'The mod does not contain a complete compiled shader package.'
}
foreach ($name in $archives) {
    $relative = 'Engine/' + $name
    $expected = $report.files.PSObject.Properties[$relative].Value
    $actual = Get-Sha256 (Join-Path $shader $relative)
    if ($actual -ine $expected) { throw "Shader package changed: $name. Rebuild it before launching." }
}
if ((Get-Sha256 (Join-Path $game 'Engine/Shaders.pak')) -ine $report.source) {
    throw 'Retail shaders changed since this mod was compiled. Rebuild the shader package for this game version.'
}
$exeRelative = 'Bin/Win64MasterMasterSteamPGO/KingdomCome.exe'
foreach ($required in @($exeRelative, 'Bin/Win64Shared', 'Engine/Engine.pak', 'Data', 'Localization', 'system.cfg')) {
    if (-not (Test-Path -LiteralPath (Join-Path $game $required))) { throw "Missing retail input: $required" }
}

# A sibling avoids recursive links through the installed mod, and is ignored by
# the mod manager because it has no mod.manifest. Refresh this one view in place.
$root = Join-Path $mods ('.' + $identity + '-runtime')
$marker = Join-Path $root 'runtime-owner.json'
if (Test-Path -LiteralPath $root) {
    $item = Get-Item -LiteralPath $root -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Runtime root must not be a junction or symlink.' }
    if (-not (Test-Path -LiteralPath $marker)) { throw "Refusing to replace an unowned directory: $root" }
    $owner = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($owner.owner -ne $identity -or $owner.game -ine $game) { throw 'Runtime ownership does not match this install.' }
}

function Remove-PrivateEntry([string]$Path) {
    # Check the absolute entry path before removal. Never traverse junctions:
    # Data/Localization point at retail and must only have their links removed.
    $absolute = [IO.Path]::GetFullPath($Path)
    if (-not $absolute.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing removal outside the owned runtime: $absolute"
    }
    $entry = Get-Item -LiteralPath $absolute -Force
    if ($entry.PSIsContainer) {
        if (-not ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            foreach ($child in Get-ChildItem -LiteralPath $absolute -Force) { Remove-PrivateEntry $child.FullName }
        }
        $entry.Delete() # Nonrecursive: detach a junction without touching its target.
    } else { $entry.Delete() }
}
if (-not (Test-Path -LiteralPath $root)) { New-Item -ItemType Directory -Path $root | Out-Null }
foreach ($entry in Get-ChildItem -LiteralPath $root -Force) {
    if ($entry.Name -ne 'runtime-owner.json') { Remove-PrivateEntry $entry.FullName }
}
@{schema=1; owner=$identity; game=$game; mod=$mod} | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8

$links = [Collections.Generic.List[object]]::new()
function Add-Input([string]$Source, [string]$Relative, [string]$Kind) {
    $destination = Join-Path $root $Relative
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force | Out-Null
    if ($Kind -eq 'Copy') {
        Copy-Item -LiteralPath $Source -Destination $destination
    } else {
        # No copy fallback: linking failure must never duplicate the game library.
        New-Item -ItemType $Kind -Path $destination -Target $Source | Out-Null
    }
    $links.Add(@{path=$Relative; source=$Source; kind=$Kind})
}
# Levels must be discoverable under the canonical Data/Levels root. Retail's
# mod-relative discovery otherwise resolves level-local AI data differently.
# Project Data rather than editing retail: old runtimes with a Data junction
# are detached by Remove-PrivateEntry above, without traversing their target.
$levelRoot = Join-Path $mod 'Data/Levels'
$modLevels = @{}
if (Test-Path -LiteralPath $levelRoot) {
    foreach ($level in Get-ChildItem -LiteralPath $levelRoot -Directory) {
        if (Test-Path -LiteralPath (Join-Path $level.FullName 'level.pak')) {
            $modLevels[$level.Name] = $level.FullName
        }
    }
}
foreach ($entry in Get-ChildItem -LiteralPath (Join-Path $game 'Data')) {
    if ($entry.Name -ieq 'Levels' -and $entry.PSIsContainer) {
        foreach ($level in Get-ChildItem -LiteralPath $entry.FullName) {
            if ($modLevels.ContainsKey($level.Name)) {
                # Accept the earlier diagnostic alias, but never shadow a native level.
                $isAlias = ($level.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
                    ([IO.Path]::GetFullPath($level.Target[0]).TrimEnd('\') -ieq $modLevels[$level.Name].TrimEnd('\'))
                if ($isAlias) { continue }
                # Native-level mod packages (for example travel edits in
                # trosecko) remain normal overlays; expose the native base here.
                $modLevels.Remove($level.Name)
            }
            $kind = if ($level.PSIsContainer) { 'Junction' } else { 'HardLink' }
            Add-Input $level.FullName ('Data/Levels/' + $level.Name) $kind
        }
    } else {
        $kind = if ($entry.PSIsContainer) { 'Junction' } else { 'HardLink' }
        Add-Input $entry.FullName ('Data/' + $entry.Name) $kind
    }
}
foreach ($name in $modLevels.Keys) {
    Add-Input $modLevels[$name] ('Data/Levels/' + $name) 'Junction'
}
Add-Input (Join-Path $game 'Localization') 'Localization' 'Junction'
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $game 'Bin') -File -Recurse) {
    # DLLs/executables are immutable inputs; never share logs or writable config.
    $relative = $file.FullName.Substring($game.Length + 1)
    if ($file.Extension -in @('.exe', '.dll')) { Add-Input $file.FullName $relative 'HardLink' }
    elseif ($file.Extension -in @('.dat', '.json', '.cfg', '.txt')) { Add-Input $file.FullName $relative 'Copy' }
}
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $game 'Engine') -File -Filter '*.pak') {
    if ($file.Name -notin $archives) { Add-Input $file.FullName ('Engine/' + $file.Name) 'HardLink' }
}
foreach ($name in $archives) { Add-Input (Join-Path $shader ('Engine/' + $name)) ('Engine/' + $name) 'HardLink' }
foreach ($name in @('system.cfg', 'user.cfg', 'whdlversions.json')) {
    $source = Join-Path $game $name
    if (Test-Path -LiteralPath $source) { Add-Input $source $name 'Copy' }
}
# Project each installed mod's normal loadable inputs. Do not link the entire
# Mods folder back into itself. Retain ordering and other users' mods unchanged.
foreach ($directory in Get-ChildItem -LiteralPath $mods -Directory) {
    if (-not (Test-Path -LiteralPath (Join-Path $directory.FullName 'mod.manifest'))) { continue }
    foreach ($name in @('mod.manifest', 'mod.cfg')) {
        $source = Join-Path $directory.FullName $name
        if (Test-Path -LiteralPath $source) { Add-Input $source ('Mods/' + $directory.Name + '/' + $name) 'Copy' }
    }
    foreach ($name in @('Data', 'Localization')) {
        $source = Join-Path $directory.FullName $name
        if (Test-Path -LiteralPath $source) { Add-Input $source ('Mods/' + $directory.Name + '/' + $name) 'Junction' }
    }
}
if (Test-Path -LiteralPath (Join-Path $mods 'mod_order.txt')) {
    Add-Input (Join-Path $mods 'mod_order.txt') 'Mods/mod_order.txt' 'Copy'
}
$launch = @{
    schema=1; root=$root; executable=(Join-Path $root $exeRelative); links=$links.ToArray()
    shader_files=$report.files; native_files_replaced=0; runtime_verified=$false
}
$launch | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $root 'launch.json') -Encoding UTF8
if ($PrepareOnly) { $launch | ConvertTo-Json -Depth 5; exit 0 }
if (-not (Get-Process steam -ErrorAction SilentlyContinue)) {
    throw 'Start Steam and sign in to the account that owns KCD2, then use this launcher.'
}
# This is the interactive game requested by the person using this launcher.
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $launch.executable
$start.WorkingDirectory = $root
$start.UseShellExecute = $false
# The private executable path is outside Steam's ordinary launch entry. Supply
# the real game's app context; its unchanged Steam API still authenticates it.
$start.EnvironmentVariables['SteamAppId'] = '1771300'
$start.EnvironmentVariables['SteamGameId'] = '1771300'
if ($StartupCheck) {
    # A bounded mount check, without loading a save or entering a level.
    $start.Arguments = '-unattended -no_splash +sys_intromoviesduringinit 0 +quit'
    $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
}
$process = [Diagnostics.Process]::Start($start)
if ($StartupCheck) {
    if (-not $process.WaitForExit(60000)) {
        $process.Kill(); $process.WaitForExit()
        throw "Shader startup check timed out; see $root\kcd.log"
    }
    if ($process.ExitCode -ne 0) { throw "Shader startup check exited with code $($process.ExitCode); see $root\kcd.log" }
    $log = Get-Content -LiteralPath (Join-Path $root 'kcd.log') -Raw
    foreach ($name in $archives) {
        $mounted = "Pak 'engine\" + $name.ToLowerInvariant() + "' is opened"
        if (-not $log.Contains($mounted)) { throw "Shader archive was not mounted: $name" }
    }
    if (-not $log.Contains('Successfully initialized Steam API') -or -not $log.Contains('Quit requested')) {
        throw 'Startup did not reach the requested clean exit after Steam initialization.'
    }
    Write-Output "Retail startup mounted all four mod shader archives and exited cleanly. Log: $root\kcd.log"
    exit 0
}
@{pid=$process.Id; root=$root; log=(Join-Path $root 'kcd.log'); native_files_replaced=0} | ConvertTo-Json
