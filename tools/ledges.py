"""Restore KCD1 vault/climb ledges with KCD2's native LedgeManager contract.

Both games compile ledges into whdata_1 Root/LedgeManager with identical Ledge
and Marker records in world space. Static ledges (entityId 0) are copied as-is;
entity-bound ledges follow their source LedgeObject, which is re-created with a
fresh converted EntityId, or are dropped with the inactive source layer.
"""
import copy
import math
import xml.etree.ElementTree as ET
from collections import Counter

from chairs import inventory
from cooking_pots import vector
from entity_visuals import world_transform
from upgrade_map import read, xml

PREFIX = 'gm_ledge_'
LEVEL_FILES = ('objects_mission0.xml', 'whdata_1')
LEDGE = ('entityId', 'markersStartIdx', 'markersCount', 'ledgeCornerEndAdjustAmount', 'Flags0', 'Flags1')
MARKER = ('worldPosition', 'facingDirection', 'endOrCorner')


def manager(root, what):
    node = root.find('LedgeManager')
    if node is None or [c.tag for c in node] != ['Ledges', 'Markers']:
        raise ValueError(what + ': unexpected LedgeManager layout')
    ledges, markers = node
    for record, fields in ((ledges, LEDGE), (markers, MARKER)):
        if any(tuple(c.tag for c in r) != fields for r in record):
            raise ValueError(what + ': unexpected ' + record.tag[:-1] + ' fields')
    start = 0
    for l in ledges:
        first, count = int(l.findtext('markersStartIdx')), int(l.findtext('markersCount'))
        if first != start or count < 2: raise ValueError(what + ': non-contiguous ledge markers')
        start += count
        if not math.isfinite(float(l.findtext('ledgeCornerEndAdjustAmount'))): raise ValueError(what + ': invalid ledge')
        int(l.findtext('entityId')); int(l.findtext('Flags0')); int(l.findtext('Flags1'))
    if start != len(markers): raise ValueError(what + ': marker count mismatch')
    for m in markers:
        values = [float(v) for f in MARKER[:2] for v in m.findtext(f).split(',')]
        if len(values) != 6 or not all(map(math.isfinite, values)) or m.findtext('endOrCorner') not in ('0', '1'):
            raise ValueError(what + ': invalid ledge marker')
    return ledges, markers


def convert(files, source, native, guid):
    root = ET.fromstring(files['objects_mission0.xml'])
    meta = ET.fromstring(files['whdata_1']) if 'whdata_1' in files else None
    if any(e.get('Name', '').startswith(PREFIX) for e in root.iter('Entity')) or (
            meta is not None and meta.find('LedgeManager') is not None):
        raise ValueError('Ledges already converted; use the pre-conversion baseline')
    native_meta = ET.fromstring(read(native, 'whdata_1'))
    manager(native_meta, 'native')
    if [c.tag for c in native_meta][:1] != ['LedgeManager']:
        raise ValueError('Native whdata_1 no longer leads with LedgeManager')
    if meta is None: meta = ET.Element('Root', native_meta.attrib)
    if meta.tag != 'Root' or meta.attrib != native_meta.attrib or meta.find('LedgeManager') is not None:
        raise ValueError('Unexpected destination whdata_1 root')
    ledges, markers = manager(ET.fromstring(read(source, 'whdata_1')), 'source')
    entities, active, deferred = inventory(source, 'LedgeObject')
    active = {e.get('EntityId'): e for e in active}
    inactive = {d['source_id']: d['layer'] for d in deferred}
    used = Counter(l.findtext('entityId') for l in ledges)
    next_id = max((int(e.get('EntityId', '0')) for e in root.iter('Entity')), default=0) + 1
    remap, records = {'0': '0'}, []
    for key in sorted(active, key=int):
        if key not in used: continue
        original = active[key]
        if original.findall('EntityLinks/Link'): raise ValueError(f'LedgeObject {key}: source links require conversion')
        p, q, scale = world_transform(original, entities)
        node = ET.Element('Entity', Name=PREFIX+key, Pos=vector(p), Rotate=vector(q), EntityClass='LedgeObject',
                          EntityId=str(next_id), EntityGuid=guid('ledge/'+key), CastShadowMinSpec='1')
        if any(abs(s-1) > 1e-5 for s in scale): node.set('Scale', vector(scale))
        node.append(copy.deepcopy(original.find('Properties')))
        root.append(node)
        remap[key] = str(next_id); next_id += 1
        records.append(dict(source_id=key, entity_id=remap[key], entity_guid=node.get('EntityGuid'), position=list(p)))
    out = ET.Element('LedgeManager')
    kept_ledges, kept_markers = ET.SubElement(out, 'Ledges'), ET.SubElement(out, 'Markers')
    skipped, layers = Counter(), Counter()
    for l in ledges:
        key = l.findtext('entityId')
        if key not in remap:
            reason = 'inactive_layer' if key in inactive else 'non_ledge_entity' if key in entities else 'missing_entity'
            skipped[reason] += 1
            if key in inactive: layers[inactive[key]] += 1
            continue
        first, count = int(l.findtext('markersStartIdx')), int(l.findtext('markersCount'))
        record = copy.deepcopy(l)
        record.find('entityId').text = remap[key]
        record.find('markersStartIdx').text = str(len(kept_markers))
        kept_ledges.append(record)
        kept_markers.extend(copy.deepcopy(m) for m in markers[first:first+count])
    meta.insert(0, out)
    result = dict(files, **{'objects_mission0.xml': xml(root), 'whdata_1': xml(meta)})
    static = sum(l.findtext('entityId') == '0' for l in kept_ledges)
    return result, dict(ledges=len(kept_ledges), static_ledges=static, entity_ledges=len(kept_ledges)-static,
                        markers=len(kept_markers), entities=len(records), source_ledges=len(ledges),
                        source_markers=len(markers), skipped=dict(sorted(skipped.items())),
                        skipped_layers=dict(sorted(layers.items())),
                        unreferenced_entities=sorted(set(active) - set(used), key=int),
                        records=records, runtime_verified=False)


def build(files, source, target, guid):
    import zipfile
    from pathlib import Path
    source, target = Path(source), Path(target)
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as src, \
         zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native:
        return convert(files, src, native, guid)
