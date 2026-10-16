# Dev Illum shader compilation repair

The 16 October 2026 live log reports `implicit truncation of vector type`
with `-Werror,-Wconversion`, followed by failure to compile
`illum@illuminationps(x2)(210000002031)`.

The bundled `Engine/Shaders.pak: Shaders/HWScripts/CryFX/Illum.cfx` has two
invalid calls in its SILHOUETTE_PARALLAX_OCCLUSION_MAPPING branches (source
lines 692 and 862). `textureLib.cfi` declares GetDiffuseTex with float2 texture
coordinates and a four-component return. Repair the UV argument to baseTC.xy
at both calls and explicitly take .rgb for the three-component Albedo target.
Alpha continues to use .w. Do not disable compiler warnings or material features.

`tools/fix_illum_shader.py --game <KCD2Mod>` installs a loose Illum.cfx override,
refusing an unrecognized existing override. The bundled archive is unchanged.
Only the two calls differ from the installed source. Generated engine shader
source stays outside the repository.

A minimal HLSL reproduction compiled with DXC ps_6_2 and -WX fails before the
change with the reported truncation errors and compiles after the change.
Evidence is in outputs/illum-shader-fix. This is an isolated compiler check,
not a full engine-permutation or visual test. The running game must reload its
shaders or restart before the installed source change takes effect. Expect
one-time recompilation of affected Illum variants; this does not itself fix
shared retail/dev shader-cache invalidation.
