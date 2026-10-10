param(
    [string]$EditorRoot = 'D:\SteamLibrary\steamapps\common\KCD2Mod',
    [string]$EvidenceRoot = 'D:\KingdomComeGlueMapper\outputs\BuildWork\fritz-editor-control'
)
$ErrorActionPreference = 'Stop'
$levelRoot = Join-Path $EditorRoot 'Data\Levels\fritz_editor_control'
$exe = Join-Path $EditorRoot 'Bin\Win64ReleaseSteamLTO_DLL\Editor.exe'
if (Get-Process Editor -ErrorAction SilentlyContinue) { throw 'Close Sandbox before exporting.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runRoot = Join-Path $EvidenceRoot "export-$stamp"
New-Item -ItemType Directory -Path $runRoot | Out-Null
$cry = 'Data\Levels\fritz_editor_control\fritz_editor_control.cry'
$stages = @{
    hlod = "-layerExportProfile game -exportHLodTree $cry -unattended -ignoreAssert -TraceNoServer"
    level = "-useHDDForILAO -useILAOFolder AOData_builder -unattended -noSourceControl -noRender -mandatoryPaks -TraceNoServer -ignoreAssert +s_AudioSystemImplementationName nic ++sys_parallel_processing 0 ++wh_concept_strictPortValidation 0 ++wh_ai_PathMNMValidationFailIsError 1 ++r_BreakOnError 0 ++wh_sys_PakExportEmbedZlibHeader 1 ++wh_sys_PakExportAlignmentUsingZlibHeader 1 -layerExportProfile game -export $cry"
}
foreach ($stage in @('hlod','level')) {
    if ($stage -eq 'level' -and (Test-Path -LiteralPath "$levelRoot\level.pak")) {
        $resolved = (Resolve-Path -LiteralPath "$levelRoot\level.pak").Path
        if ($resolved -ne "$levelRoot\level.pak") { throw 'Unexpected export path' }
        Move-Item -LiteralPath $resolved -Destination "$runRoot\previous-level.pak"
    }
    Write-Output "Starting $stage"
    $proc = Start-Process -FilePath $exe -WorkingDirectory $EditorRoot -ArgumentList $stages[$stage] -WindowStyle Hidden -Wait -PassThru
    Copy-Item -LiteralPath "$EditorRoot\editor.log" -Destination "$runRoot\$stage.log"
    if ($proc.ExitCode -ne 0) { throw "$stage exit code $($proc.ExitCode)" }
    $log = Get-Content -LiteralPath "$runRoot\$stage.log" -Raw
    if ($log -match 'HLodTree generation error|Unable to export|Export failed|NPC without Home link') { throw "$stage failed; inspect log" }
    Write-Output "Completed $stage"
}
$rcArgs = '/ZlibHeaderMaintainAlignment=1 /threads=8 /crashOnAssert /p=PC /zip_encrypt=0 /branch=main /verbose=0 /EmbedZlibHeader=1 /jobtarget= /job=Tools/rc/RcJob_WH_level.xml /LevelPath=Data/Levels/fritz_editor_control'
$rc = Start-Process -FilePath "$EditorRoot\Tools\rc\rc.exe" -WorkingDirectory $EditorRoot -ArgumentList $rcArgs -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$runRoot\rc.log" -RedirectStandardError "$runRoot\rc-error.log"
if ($rc.ExitCode -ne 0) { throw "Resource Compiler exit code $($rc.ExitCode)" }
foreach ($required in @('hlodtree.xml','level.pak','terrain.pak','recast.pak')) {
    if (-not (Test-Path -LiteralPath "$levelRoot\$required")) { throw "Missing $required" }
}
if ((Get-Item -LiteralPath "$levelRoot\recast\rdnavmesh_1.nav").Length -le 60) { throw 'Navigation mesh is empty' }
Write-Output "Export complete. Evidence: $runRoot"
