param(
    [Parameter(Mandatory=$true)][string]$GameRoot,
    [string]$SaveName,
    [ValidateRange(0,3)][int]$Playline = 0,
    [int]$CompatibilityVersion = -1,
    [switch]$FreezePlayline
)
$ErrorActionPreference = 'Stop'
if (Get-Process KingdomCome -ErrorAction SilentlyContinue) {
    throw 'Close KCD2 before starting the save compatibility test.'
}
if ($SaveName -and $SaveName -notmatch '^[a-zA-Z0-9_-]+\.whs$') {
    throw 'SaveName must be a .whs filename, not a path.'
}
$exe = Join-Path $GameRoot 'Bin\Win64ReleaseSteamLTO_DLL\KingdomCome.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Mod Tools executable missing: $exe" }
if ($SaveName) {
    $save = Join-Path "$env:USERPROFILE\Saved Games\kingdomcome2\saves" "playline$Playline\$SaveName"
    if (-not (Test-Path -LiteralPath $save -PathType Leaf)) { throw "Save missing: $save" }
}
# Native coach travel must write a LevelSwitchSave before changing regions.
# Freezing the playline allows the initial load but aborts that transition.
$freezeValue = [int]$FreezePlayline.IsPresent
$arguments = @('-devmode', '+wh_sys_FreezePlayline', $freezeValue.ToString(), '+wh_sys_NoPlaylineDeleting', '1',
    '+r_Fullscreen', '0', '+r_Width', '1280', '+r_Height', '720',
    '+g_skipIntro', '1', '+sys_intromoviesduringinit', '0', '+wh_sys_SkipStartupVideoWhenPossible', '1')
if ($SaveName -and $CompatibilityVersion -ne -1) {
    $arguments += @('+wh_sys_FakeLoadedGameVersion', "$CompatibilityVersion")
}
if ($SaveName) { $arguments += @('+wh_sys_LoadGame', "$Playline", $SaveName) }
$start = [Diagnostics.ProcessStartInfo]::new($exe)
$start.WorkingDirectory = (Resolve-Path -LiteralPath $GameRoot).Path
$start.UseShellExecute = $false
foreach ($argument in $arguments) { $start.ArgumentList.Add($argument) }
# Query the signed-in Steam account's real KCD2 DLC entitlements. Under the
# Modding Tools app ID the same DLCs are reported inactive. No license overrides.
$start.Environment['SteamAppId'] = '1771300'
$start.Environment['SteamGameId'] = '1771300'
if ($SaveName) { $hash = (Get-FileHash -LiteralPath $save -Algorithm SHA256).Hash }
$game = [Diagnostics.Process]::Start($start)
Write-Output "Mod Tools save test started windowed (PID $($game.Id)). FreezePlayline=$freezeValue; New Game playline deletion is disabled."
if ($SaveName) {
    Write-Output "Save: $save"
    Write-Output "Save SHA256: $hash"
} else {
    Write-Output 'Fresh session: choose New Game. No saved game will be loaded.'
}
Write-Output "Log: $(Join-Path $GameRoot 'kcd.log')"
if ($SaveName -and $CompatibilityVersion -ne -1) {
    Write-Output 'Loading a newer save through the compatibility override is a test, not proof of format compatibility.'
}
