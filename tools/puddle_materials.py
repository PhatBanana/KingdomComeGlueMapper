"""Convert shallow muddy-puddle proxies without changing their visible material."""
from pathlib import PurePosixPath


def convert_puddle_proxies(material):
    """Match the native KCD2 mud-puddle proxy surface; return changed slot count.

    Require a dedicated muddy decal material with puddle textures. Mixed water
    materials, ordinary mud, and actual water shaders must keep their physics.
    """
    slots = material.findall('SubMaterials/Material')
    visible = [m for m in slots if m.get('Shader', '').lower() != 'nodraw']
    if not visible or not all(
        m.get('Shader', '').lower() == 'illum'
        and m.get('SurfaceType') == 'mat_mudwater'
        and 'DECAL' in m.get('StringGenMask', '').split('%')
        and any(t.get('Map') == 'Diffuse' and 'puddle' in
                PurePosixPath(t.get('File', '').replace('\\', '/')).name.lower()
                for t in m.findall('Textures/Texture'))
        for m in visible
    ):
        return 0
    changed = 0
    for slot in slots:
        if slot.get('Shader', '').lower() == 'nodraw' and slot.get('SurfaceType') == 'mat_water':
            slot.set('SurfaceType', 'mat_mudwater')
            changed += 1
    return changed
