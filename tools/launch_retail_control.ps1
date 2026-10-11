param(
    [ValidateSet('Menu','Direct')][string]$Mode = 'Menu',
    [string]$GameRoot = 'D:\SteamLibrary\steamapps\common\KingdomComeDeliverance2',
    [string]$EvidenceRoot = 'D:\KingdomComeGlueMapper\outputs\BuildWork\fritz-systems-control-retail\sessions'
)
$ErrorActionPreference = 'Stop'
if (Get-Process KingdomCome -ErrorAction SilentlyContinue) { throw 'KCD2 is already running. Close it before launching another session.' }
$modRoot = Join-Path $GameRoot 'Mods\kingdomcomegluemapper'
$receipt = Get-Content -LiteralPath (Join-Path $modRoot 'gluemapper-install.json') -Raw | ConvertFrom-Json
if ($receipt.systems_control.level -ne 'fritz_systems_control') { throw 'The systems control is not installed.' }
$levelPak = Join-Path $modRoot 'Data\Levels\fritz_systems_control\level.pak'
$hash = (Get-FileHash -LiteralPath $levelPak -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hash -ne $receipt.systems_control.packaged_level_sha256) { throw 'Installed control level changed.' }
$runRoot = Join-Path $EvidenceRoot ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $Mode.ToLowerInvariant())
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$previousLog = Join-Path $GameRoot 'kcd.log'
if (Test-Path -LiteralPath $previousLog) { Copy-Item -LiteralPath $previousLog -Destination (Join-Path $runRoot 'previous-kcd.log') }
$arguments = @('-devmode', '+g_skipIntro', '1')
if ($Mode -eq 'Direct') { $arguments += @('+map','fritz_systems_control') }
@{
    mode = $Mode
    level_sha256 = $hash
    started = (Get-Date -Format o)
    runtime_verified = $false
    player_state_warning = 'Direct startup can create a fresh Henry. For a closer comparison, load the same Trosky save at the menu, then enter map fritz_systems_control in the console. Compare inventory and perks before interpreting combat.'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'session.json') -Encoding utf8
$exe = Join-Path $GameRoot 'Bin\Win64MasterMasterSteamPGO\KingdomCome.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Retail executable not found: $exe" }
# This is the interactive game the user requested, not a background helper.
$game = Start-Process -FilePath $exe -WorkingDirectory $GameRoot -ArgumentList $arguments -WindowStyle Normal -PassThru
Write-Output "Retail KCD2 started (PID $($game.Id)); mode: $Mode"
Write-Output "Evidence: $runRoot"
Write-Output 'Coach test: load the Trosky save and choose Travel to Test world.'
Write-Output 'Direct comparison: reload that Trosky save, then console: map fritz_systems_control'
Write-Output 'Before fighting, console: exec gm_combat_log_start.cfg'
