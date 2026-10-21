"""Convert observed static brush records without changing their transforms."""
import math
import struct

# KCD1 serialized static-instancing bit. The imported brushes are ordinary
# KCD2 HLOD placements, not members of a rebuilt native instancing graph.
LEGACY_STATIC_INSTANCING = 1 << 20


# Explicitly audited visible materials in the excluded level-local brush set.
# Other designer solids include collision barriers and giant editor helpers.
LANDSCAPE_DESIGNER_MATERIALS = {
    'objects/nature/rocks/rocks_modular/rock_modular_05',
    'objects/nature/rocks/rocks_modular/rock_modular_16_darker',
    'objects/structures/platforms/tanner_canal_ground',
    'materials/terrain/river/river_bottom_03_for_designer_box',
}

# KCD1 sandbox designer volumes whose whole purpose is blocking or guiding
# movement. KCD2 ships the same materials under identical paths with matching
# SurfaceTypes (mat_level_barrier, mat_player_only, mat_horse_only,
# mat_deep_water_barrier, mat_barrier_navignore, mat_nodraw_designer, ...), and
# native trosecko places its own collision volumes as plain HLOD brush records
# carrying these materials, so a converted record with the material baked into
# the mesh keeps the authored surface-type semantics.
COLLISION_PROXY_MATERIALS = {
    'materials/special/collision_proxy_horseonly',
    'materials/special/collision_proxy_material',
    'materials/special/collision_proxy_player_only',
    'materials/special/collision_proxy_deep_water_barrier',
    'materials/special/collision_proxy_level_barrier',
    'materials/special/collision_proxy_material_navignore',
    'materials/special/collision_proxy_material_puddle',
    'materials/special/collision_proxy_return_to_skalice_barrier',
    'materials/special/collision_proxy_counterfeiters_barrier',
    'materials/special/collision_proxy_entitiesonly',
}


def is_landscape_designer(path, material):
    return (path.replace('\\', '/').lower().startswith('%level%/brush/designer_')
            and material.replace('\\', '/').lower().removesuffix('.mtl') in LANDSCAPE_DESIGNER_MATERIALS)


def is_collision_designer(path, material):
    """Designer volume with an authored collision/barrier surface type."""
    return (path.replace('\\', '/').lower().startswith('%level%/brush/designer_')
            and material.replace('\\', '/').lower().removesuffix('.mtl') in COLLISION_PROXY_MATERIALS)


def is_uberlod_proxy(path):
    """World-distance stand-ins belong to the switching graph, not static props."""
    # Forest proxies use uber/, while town/building proxies use uberlods/.
    # Both are FarObjects in terrain/uberlods.xml, not per-model LOD files.
    return path.replace('\\', '/').lower().startswith(('objects/uber/', 'objects/uberlods/'))


def read_brush(data, offset, mesh_paths, material_paths):
    if offset + 100 > len(data) or struct.unpack_from("<I", data, offset)[0] != 1:
        raise ValueError("Invalid source brush")
    mesh = struct.unpack_from("<H", data, offset + 36)[0]
    material = struct.unpack_from("<i", data, offset + 92)[0]
    transform = struct.unpack_from("<12f", data, offset + 40)
    if mesh >= len(mesh_paths) or material < -1 or material >= len(material_paths):
        raise ValueError("Invalid brush resource reference")
    if not all(map(math.isfinite, transform)):
        raise ValueError("Invalid brush transform")
    return {"offset": offset, "mesh": mesh, "path": mesh_paths[mesh].lower(),
            "material": material, "layer": struct.unpack_from("<H", data, offset + 28)[0],
            "position": [transform[3], transform[7], transform[11]]}


def convert_brush(data, offset, mesh, material):
    # Intermediate record: lod_ratio_metadata finalizes the source LOD byte
    # after all world stages, so cached and newly imported records cannot mix.
    old = data[offset:offset + 100]
    if len(old) != 100 or struct.unpack_from("<I", old)[0] != 1:
        raise ValueError("Invalid source brush")
    if not 0 <= mesh <= 65535 or material < -1:
        raise ValueError("Invalid target brush resource reference")
    result = bytearray(old[:36] + bytes(4) + old[36:])
    struct.pack_into("<H", result, 28, 0)
    struct.pack_into("<H", result, 40, mesh)
    struct.pack_into("<H", result, 92, 0)  # neutral KCD2 collision class
    struct.pack_into("<i", result, 96, material)
    # State selection is explicit in the builder; make selected brushes visible.
    flags = struct.unpack_from("<Q", result, 32)[0]
    struct.pack_into("<Q", result, 32, flags & ~((1 << 8) | LEGACY_STATIC_INSTANCING))
    if result[44:92] != old[40:88]:
        raise ValueError("Brush transform changed")
    return bytes(result)


def resource_table(paths):
    result = bytearray(struct.pack("<I", len(paths)))
    for path in paths:
        encoded = path.encode()
        if len(encoded) >= 256:
            raise ValueError("Resource path too long")
        result.extend(encoded.ljust(256, b"\0"))
    return result
