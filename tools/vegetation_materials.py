"""Convert legacy tree shadow proxies without changing mesh material indices."""
import copy


def native_vine_deformation(document, native):
    """Use the matching KCD2 wall vine's authored motion, retaining appearance."""
    deform = native.find('VertexDeform')
    if native.get('Shader', '').lower() != 'vegetation' or deform is None:
        raise ValueError('Expected native vine vegetation deformation')
    for previous in list(document.findall('VertexDeform')):
        document.remove(previous)
    document.append(copy.deepcopy(deform))
    document.set('vertModifType', native.get('vertModifType', '0'))
    source_params = native.find('PublicParams')
    params = document.find('PublicParams')
    if source_params is not None:
        if params is None:
            import xml.etree.ElementTree as ET
            params = ET.SubElement(document, 'PublicParams')
        for key, value in source_params.attrib.items():
            if key.startswith('bendDetail'):
                params.set(key, value)


def convert_shadow_proxies(document):
    """Use visible foliage for shadows instead of a legacy duplicate canopy.

    Legacy tree CGFs include shadow_proxy subsets alongside their visible
    subsets, even in LOD0. This candidate addresses coarse proxy polygons
    appearing in the target camera pass; visual validation is pending. Keep every slot
    in place, hide only explicitly named vegetation shadow proxies, and allow
    the corresponding visible vegetation to cast shadows. This trades the
    cheap dedicated shadow mesh for correct visible geometry.
    """
    converted = 0
    for submaterials in document.iter('SubMaterials'):
        proxies = [m for m in submaterials
                   if m.get('Name', '').lower() in ('shadow_proxy', 'shadowproxy')
                   and m.get('Shader', '').lower() == 'vegetation']
        if not proxies:
            continue
        for material in submaterials:
            if material in proxies:
                material.set('Shader', 'Nodraw')
                material.set('GenMask', '0')
                material.set('StringGenMask', '')
                material.set('MtlFlags', str(int(material.get('MtlFlags', '0')) | 0x400))
                converted += 1
            elif material.get('Shader', '').lower() == 'vegetation':
                # MTL_FLAG_NOSHADOW. Preserve every other material flag.
                material.set('MtlFlags', str(int(material.get('MtlFlags', '0')) & ~0x20))
    return converted
