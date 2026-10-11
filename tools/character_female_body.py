"""Complete native female body foundation for converted source outfits.

KCD1's s2_body contains detached limbs, not the torso required by KCD2's
open-neck dresses. Keep the native body mesh and its matching UV/material pair.
Source heads, hair and garments remain separate imported components.
"""
import xml.etree.ElementTree as ET

from character_native_materials import reference
from upgrade_map import xml


def complete_female_body(output, component, assets):
    if component.get('Gender') != 'Female' or component.get('Race') != 'Human':
        raise ValueError('A human female component is required')
    bodies = component.findall('DerivedComponents/Body')
    if len(bodies) != 1:
        raise ValueError('Expected one imported female body')
    body = bodies[0]
    old = body.find('Elements/SkinElement')
    folder = output / 'objects/characters' / component.get('FilePath')
    source_material = ET.parse(folder / old.get('Material')).getroot()
    native_base = 'objects/characters/humans/female/body/female_body_01'
    material = reference(assets, native_base + '.mtl')
    # Copy skin colour, not source textures: the native body has different UVs.
    if source_material.get('Diffuse'):
        material.set('Diffuse', source_material.get('Diffuse'))
    src_params, dst_params = source_material.find('PublicParams'), material.find('PublicParams')
    if src_params is not None and dst_params is not None and src_params.get('Melanin'):
        dst_params.set('Melanin', src_params.get('Melanin'))
    model, provenance = assets.get(native_base + '.skin')
    (folder / 'native_body.skin').write_bytes(model)
    (folder / 'native_body.mtl').write_bytes(xml(material))
    for lod in (1, 2, 3, 4):
        path = native_base + f'_lod{lod}.skin'
        if path in assets.index:
            (folder / f'native_body_lod{lod}.skin').write_bytes(assets.get(path)[0])
    elements = body.find('Elements')
    elements.clear()
    ET.SubElement(elements, 'SkinElement', EquipmentPart='torso',
                  Model='native_body.skin', Material='native_body.mtl',
                  BodyLayerId='0', KeepBodyLayer='true', IsFinalLayer='false')
    return dict(model=native_base + '.skin', provenance=provenance,
                policy='Complete native female body with matching native UVs and source skin colour')
