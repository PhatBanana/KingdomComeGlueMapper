"""Translate KCD1 Waterfall material scroll rates to the KCD2 time base."""
import math
import xml.etree.ElementTree as ET


def convert_waterfall_speeds(material):
    """Apply once to a source KCD1 material, never to an already converted one.

    KCD1 Waterfall.cfx uses AnimParams.x = PB_time * 0.0125.
    KCD2 Waterfall.cfx uses CV_AnimGenParams.w, the shared time * 0.125.
    Both layers multiply that timer by SpeedLayerN. Preserve authored UV
    velocity, direction and tiling by compensating only those two rates.
    Water/WaterVolume have different animation paths and are not adjusted.
    """
    changes = []
    for slot in material.iter('Material'):
        if slot.get('Shader', '').lower() != 'waterfall':
            continue
        params = slot.find('PublicParams')
        if params is None:
            params = ET.SubElement(slot, 'PublicParams')
        for name in ('SpeedLayer0', 'SpeedLayer1'):
            # Serialize compensated source defaults (1 and 2) when a
            # source material omits the parameter.
            before = float(params.get(name, '1' if name == 'SpeedLayer0' else '2'))
            if not math.isfinite(before):
                raise ValueError(f'Non-finite {name}')
            after = before * 0.1
            params.set(name, format(after, '.9g'))
            changes.append(dict(slot=slot.get('Name', ''), parameter=name,
                                before=before, after=after))
    return changes
