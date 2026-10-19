# Gate source validation after mesh conversion

Setup 0.3.9 could reject a clean build at the gate recipe with `Gate geometry
differs from its reviewed source`. The source identity check excluded renamed
material chunks but still compared unconverted mesh-header metadata.

In the failing package, the Talmberk grate's only non-material changes were the
`HAS_FACE_AREA` flag (2 to 10) and face-area float at offset 136
(0.0009387856116518378 to 0.000937418662942946). These exactly matched
`mesh_lod_metadata.normalize` applied to the original source. Vertices and other
chunks were unchanged.

`build_open_test_gates.resolve_models` now accepts either the original chunk
signature or, for CGFs, the exact signature of the normalized original. It does
not normalize the candidate or ignore arbitrary metadata. CGAs retain the
original comparison. Unsupported source normalization still fails closed.
This shared gate builder is used by setup's gameplay recipe; no package schema
or installed geometry changes are required.

Regression coverage accepts normalized metadata with renamed materials and
rejects altered area, unrelated flags, bounds, vertex data and collision chunks.
The gate builder also passed against the actual failed clean-build package,
preserving 1,009 unrelated level archive entries. This is structural validation,
not a new in-game gate traversal test or a completed full setup build.
