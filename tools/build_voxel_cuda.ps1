param([switch]$Optix)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$out = Join-Path $repo 'outputs/cuda'
New-Item -ItemType Directory -Force $out | Out-Null
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Visual Studio C++ build tools required' }
$nvcc = (Get-Command nvcc -ErrorAction Stop).Source
$vcvars = Join-Path $vs 'VC/Auxiliary/Build/vcvars64.bat'
$source = Join-Path $PSScriptRoot 'voxel_raster_cuda.cu'
$name = if ($Optix) { 'voxel_raster_optix' } else { 'voxel_raster_cuda' }
$dll = Join-Path $out "$name.dll"
$extra = ''
$ptxBuild = ''
if ($Optix) {
    $sdk = Join-Path $repo 'outputs/optix-dev'
    if (-not (Test-Path -LiteralPath $sdk)) {
        & git clone --depth 1 --branch v9.1.0 https://github.com/NVIDIA/optix-dev.git $sdk
        if ($LASTEXITCODE) { throw 'OptiX headers download failed' }
    }
    $include = Join-Path $sdk 'include'
    $device = Join-Path $PSScriptRoot 'voxel_optix_device.cu'
    $ptx = Join-Path $out 'voxel_optix.ptx'
    $extra = "-DWITH_OPTIX -I`"$include`" -ladvapi32"
    # OptiX resolves its own PTX intrinsics; CUDA 13.3's standalone semantics
    # checker cannot resolve them. The OptiX module compiler validates this PTX.
    $ptxBuild = "`"$nvcc`" --ptx --skip-ptx-semantics-check --relocatable-device-code=true -std=c++17 --fmad=false -arch=compute_120 -I`"$include`" `"$device`" -o `"$ptx`"`r`nif errorlevel 1 exit /b %errorlevel%"
}
$batch = Join-Path $out 'build.cmd'
@"
@echo off
call "$vcvars"
if errorlevel 1 exit /b %errorlevel%
$ptxBuild
"$nvcc" -shared -O3 -std=c++17 --fmad=false -arch=sm_120 -Xcompiler /MD -Xcompiler /Zc:preprocessor $extra "$source" -o "$dll"
exit /b %errorlevel%
"@ | Set-Content -LiteralPath $batch
Push-Location $out
try { & cmd.exe /c $batch; if ($LASTEXITCODE) { throw "CUDA compilation failed: $LASTEXITCODE" } }
finally { Pop-Location }
$metadata = @{ source_sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant(); dll_sha256=(Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant(); architecture='sm_120'; fmad=$false }
if ($Optix) {
    $metadata.extra_sources=@{}
    foreach ($file in @('voxel_optix_shared.h','voxel_optix_device.cu','voxel_optix_host.h')) { $metadata.extra_sources[$file]=(Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $file) -Algorithm SHA256).Hash.ToLowerInvariant() }
    $metadata.ptx_sha256=(Get-FileHash -LiteralPath $ptx -Algorithm SHA256).Hash.ToLowerInvariant()
}
$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $out "$name.build.json")
