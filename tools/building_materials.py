"""Convert legacy building blend inputs to native Illum material data."""
from pathlib import PurePosixPath

from building_blend import decode_texture, bake_atlas, compressed_dds
from building_blend_mesh import reatlas


def blend_inputs(doc):
    children = doc.find('SubMaterials')
    materials = list(children) if children is not None else [doc]
    for number, element in enumerate(materials):
        features = element.get('StringGenMask', '').upper()
        if element.get('Shader', '').lower() != 'illum' or '%SNDUVS' not in features or '%BLENDLAYER' not in features:
            continue
        textures = element.find('Textures')
        if textures is None:
            continue
        second = textures.find("Texture[@Map='[1] Diffuse']")
        mask = textures.find("Texture[@Map='Opacity']")
        if second is not None and mask is not None:
            yield number, element, second, mask


def convert(doc, blob, target, asset_read, index):
    """Bake per geometry/material pair; shared source textures are never changed."""
    emitted = {}
    for number, element, second, mask in list(blend_inputs(doc)):
        if blob is None:
            raise ValueError('Two-UV blend conversion needs the associated building mesh: '+target)
        features=element.get('StringGenMask','')
        if ('%DETAIL_MAPPING' in features or '%DETAIL_ATLAS' in features) and '%USE_FIRST_UV_DETMAP' not in features:
            raise ValueError('Secondary-UV detail mapping requires its own atlas conversion')
        def texture(ref):
            name = str(PurePosixPath(ref.replace('\\', '/').lower()).with_suffix('.dds'))
            if name.startswith('data/') and name not in index:
                name = name[5:]
            parts = {str(i): asset_read(name+'.'+str(i)) for i in range(1, 16) if name+'.'+str(i) in index}
            return decode_texture(asset_read(name), parts)
        params = element.find('PublicParams')
        def value(key, default):
            return float(params.get(key, str(default))) if params is not None else default
        # Non-identity texture modifiers require additional source shader UV
        # semantics. Never silently bake them with the wrong correspondence.
        for slot in (second, mask):
            mod = slot.find('TexMod')
            if mod is not None and any(float(mod.get(k, str(v))) != v for k,v in
                                       [('TileU',1),('TileV',1),('OffsetU',0),('OffsetV',0),('RotateU',0),('RotateV',0),('RotateW',0)]):
                raise ValueError('Non-identity secondary/mask texture modifier needs conversion')
        blob, triangles, size = reatlas(blob, number)
        image, _ = bake_atlas(texture(second.get('File')), texture(mask.get('File'))[:,:,0]/255,
                             triangles, size, value('BlendMaskTiling',1),
                             (value('SndUVsTileU',1),value('SndUVsTileV',1)), value('BlendFactor',0))
        name = target+'_blend'+str(number)+'_diff.dds'
        emitted[name] = compressed_dds(image)
        second.set('File',name)
        if params is not None:
            params.set('SndUVsTileU','1');params.set('SndUVsTileV','1')
            if value('BlendFactor',0)<0:params.set('BlendFactor','0')
        element.find('Textures').remove(mask)
    return blob, emitted
