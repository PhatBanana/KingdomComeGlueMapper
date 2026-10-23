# World-boundary collision policy

The imported designer collision stage previously flattened local helper solids
along with the map border. Hiding their materials fixed the red debug rendering,
but did not make the open Skalitz gates passable. Source designer solids 655,
603 and 670 cross the three opened gate passages and use the ordinary
`collision_proxy_material` material, not the quest-named return-to-Skalitz
barrier. Removing only quest-named materials would miss this regression.

The static world now imports only designer brushes with the authored
`collision_proxy_level_barrier` material **and shared layer zero**. The layer is
essential: the source also has 13 fencing-ring barriers using this material on
`state1_barrier_fencing_place`. Those are not outside-map boundaries. The 58
shared-layer records form the outside map perimeter.

Fresh builds and saved-package upgrades use the same predicate in
`building_brushes.is_world_boundary_designer`. The upgrade identifies old proxy
records by their source origin, full bounds and original geometry signature
(allowing material renaming and the existing LOD metadata normalization), and
removes them from HLOD blocks. Mesh identity is retained during removal so an
unrelated visible brush with identical bounds survives. It rebuilds block
offsets and updates the validated LOD marker. It does
not remove ordinary visible hearth/building meshes or native door, well and
other interactive-object collision.

Validation on a private copy of the installed level removed 585 non-boundary
proxy records, retained all 58 outside-map barriers, added or modified no other
brush/vegetation records, and changed only `hlods.dat`, `hlods.xml` and the LOD
validation marker. A second upgrade made no changes. The installed game was not
modified; retail passage testing remains necessary.
