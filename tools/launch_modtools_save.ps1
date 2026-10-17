param(
    [Parameter(Mandatory=$true)][string]$GameRoot,
    [Parameter(Mandatory=$true)][string]$SaveName,
    [ValidateRange(0,3)][int]$Playline = 0,
    [int]$CompatibilityVersion = -1
)
$ErrorActionPreference = 'Stop'
if (Get-Process KingdomCome -ErrorAction SilentlyContinue) {
    throw 'Close KCD2 before starting the save compatibility test.'
}
if ($SaveName -notmatch '^[a-zA-Z0-9_-]+\.whs$') {
    throw 'SaveName must be a .whs filename, not a path.'
}
$exe = Join-Path $GameRoot 'Bin\Win64ReleaseSteamLTO_DLL\KingdomCome.exe'
$save = Join-Path "$env:USERPROFILE\Saved Games\kingdomcome2\saves" "playline$Playline\$SaveName"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Mod Tools executable missing: $exe" }
if (-not (Test-Path -LiteralPath $save -PathType Leaf)) { throw "Save missing: $save" }
$arguments = @('-devmode', '+wh_sys_FreezePlayline', '1', '+wh_sys_NoPlaylineDeleting', '1')
if ($CompatibilityVersion -ne -1) {
    $arguments += @('+wh_sys_FakeLoadedGameVersion', "$CompatibilityVersion")
}
$arguments += @('+wh_sys_LoadGame', "$Playline", $SaveName)
$start = [Diagnostics.ProcessStartInfo]::new($exe)
$start.WorkingDirectory = (Resolve-Path -LiteralPath $GameRoot).Path
$start.UseShellExecute = $false
foreach ($argument in $arguments) { $start.ArgumentList.Add($argument) }
# Query the signed-in Steam account's real KCD2 DLC entitlements. Under the
# Modding Tools app ID the same DLCs are reported inactive. No license overrides.
$start.Environment['SteamAppId'] = '1771300'
$start.Environment['SteamGameId'] = '1771300'
$hash = (Get-FileHash -LiteralPath $save -Algorithm SHA256).Hash
$game = [Diagnostics.Process]::Start($start)
Write-Output "Mod Tools save test started (PID $($game.Id)). Save writes are disabled for this session."
Write-Output "Save: $save"
Write-Output "Save SHA256: $hash"
Write-Output "Log: $(Join-Path $GameRoot 'kcd.log')"
Write-Output 'Loading a newer save through the compatibility override is a test, not proof of format compatibility.'
