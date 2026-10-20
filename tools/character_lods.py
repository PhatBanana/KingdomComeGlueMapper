"""Preserve authored skin LODs through the same rig and material conversion.

LOD selection remains owned by the native character manager. These helpers do
not set draw distances, force a mesh level, or change animation/AI budgets.
"""
import re
from pathlib import PurePosixPath

from clothing_regions import Skin


def source_lods(index, model):
    """Resolve a contiguous, case-insensitive family; never match another skin."""
    base = model.replace('\\', '/').lower()
    if not base.endswith('.skin') or re.search(r'_lod\d+\.skin$', base):
        raise ValueError('Expected a base skin for LOD discovery: ' + model)
    pattern = re.compile(re.escape(base[:-5]) + r'_lod(0*[1-9]\d*)\.skin$')
    result = {}
    for name in index:
        match = pattern.fullmatch(name.replace('\\', '/').lower())
        if match:
            level = int(match[1])
            if level in result:
                raise ValueError('Ambiguous source skin LOD: ' + model)
            result[level] = name
    if result and sorted(result) != list(range(1, max(result) + 1)):
        raise ValueError('Non-contiguous source skin LODs: ' + model)
    return dict(sorted(result.items()))


def filename(base, level):
    path = PurePosixPath(base)
    if path.suffix.lower() != '.skin' or not isinstance(level, int) or level < 1:
        raise ValueError('Invalid character LOD output')
    return str(path.with_name(path.stem + '_lod' + str(level) + '.skin'))


def validate_chain(base, lods, *, material_slots=None):
    """Check render/internal indices, ordering, and material slot identities."""
    previous = Skin(base)
    if material_slots is not None and material_slots < 1:
        raise ValueError('Invalid material slot count')
    def check_slots(skin):
        if material_slots is not None and any(
                int.from_bytes(s[16:20], 'little') >= material_slots for s in skin.subset_records):
            raise ValueError('Skin LOD introduces an unbound material slot')
    check_slots(previous)
    for level, blob in sorted(lods.items()):
        current = Skin(blob)
        if len(current.faces) > len(previous.faces):
            raise ValueError('Skin LOD increases triangle count at level ' + str(level))
        # An authored lower LOD can use a valid slot unused by LOD0 (hair caps
        # are one example). Validate against the material, not LOD0's subsets.
        check_slots(current)
        previous = current


def emit_regions(emitted, prefix, base_regions, lod_regions):
    """Publish each component's own family, retaining its authored base mesh."""
    for region, base in base_regions.items():
        chain = {level: regions[region] for level, regions in sorted(lod_regions.items())
                 if region in regions}
        if chain and sorted(chain) != list(range(1, max(chain) + 1)):
            raise ValueError('Character region disappears and returns in its LOD chain: ' + region)
        validate_chain(base, chain)
        base_name = prefix + '_' + region + '.skin'
        emitted[base_name] = base
        for level, blob in chain.items():
            emitted[filename(base_name, level)] = blob
