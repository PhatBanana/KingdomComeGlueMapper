# Imported stream animation timing

KCD1 and KCD2 ship different Waterfall shader timer bindings. The static asset
importer now compensates `SpeedLayer0` and `SpeedLayer1` by 0.1 when reading a
source KCD1 material. This applies to Waterfall submaterials wherever they occur,
including stream meshes, cascades and animated water in props.

Evidence from the installed shader archives:

* KCD1 `Waterfall.cfx`: `AnimParams.x` is `PB_time 0.0125`, and both layers
  multiply that component by their respective speed parameter.
* KCD2 `Waterfall.cfx`: both layers instead use `g_VS_AnimGenParams.w`.
* KCD2 `FXConstantDefs.cfi` aliases that name to `CV_AnimGenParams`.
* The shared engine implementation assigns its W component `animTime * 0.125`:
  [GraphicsPipeline.cpp](https://github.com/ValtoGameEngines/CryEngine/blob/release/Code/CryEngine/RenderDll/XRenderD3D9/GraphicsPipeline/Common/GraphicsPipeline.cpp).

The timer magnitude is supported by the upstream engine implementation, not a
capture of KCD2's constant buffer. Runtime visual acceptance remains necessary.
The correction preserves UV displacement per second under that timer convention.
Tests cover positive, negative and zero speeds, source defaults (1 and 2), both
layers and unrelated material slots. The helper is a one-time source conversion,
not an idempotent operation on already converted assets.

Water and WaterVolume shaders follow different animation paths and are excluded.
No world clock, gameplay current, buoyancy, UV tiling, textures or geometry change.
Other perceived motion differences in those shader families remain unverified.

Local rollout evidence is in ignored `outputs/RiverAudit/ScrollTiming01`: 47
material files, 55 Waterfall slots, 110 compensated speed parameters across four
packages. Original packages are backed up there. Every unrelated archive entry
was checked for unchanged CRC and size, and installed archives were hash checked.
Do not run the installed-package transformation on those corrected packages again;
rebuild through the importer from KCD1 source, or restore the baseline backups first.
