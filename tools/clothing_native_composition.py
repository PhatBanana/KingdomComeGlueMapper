"""Compose a source outfit where native clothing attachments select one region.

Overlapping source items become one regional outfit item. This deliberately
bundles their wear/removal: it does not pretend KCD2 draws independent lower
SkinElements, or bake a hidden dependency into an independently removable item.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

from character_lods import source_lods, filename, validate_chain
from character_skin_upgrade import canonicalize_skin_skeletons
from clothing_assembly import convert_fixed_outfit
from clothing_regions import Skin
from upgrade_map import xml


def merge_feature_slots(material):
    """Native feature-slot declarations belong to the entire multi-material."""
    seen = {}
    for slot in material.iter('Material'):
        for features in list(slot.findall('FeatureSlots')):
            for key, name in list(features.attrib.items()):
                if key in seen:
                    if seen[key] != name:
                        raise ValueError('Conflicting native feature slot in composed outfit: ' + key)
                    del features.attrib[key]
                else:
                    seen[key] = name
            if not features.attrib:
                slot.remove(features)
    return seen


def compose_source_regions(output, component, items, preset, layer_order):
    output = Path(output)
    folder = output / 'objects/characters' / component.get('FilePath')
    derived = component.find('DerivedComponents')
    index = {p.name.lower(): p for p in folder.glob('*.skin')}
    regions = {}
    for node in derived.findall('Clothing'):
        if not node.get('ArmorType'):
            continue  # Appearance underwear is a separate fallback binding.
        elements = node.findall('Elements/*')
        if len(elements) != 1 or elements[0].tag != 'SkinElement':
            raise ValueError('Source region composition requires explicit single-region skins')
        element = elements[0]
        order = layer_order.get(element.get('BodyLayerId'))
        if order is None:
            raise ValueError('Unknown native layer during source outfit composition')
        regions.setdefault(element.get('EquipmentPart'), []).append((order, node, element))
    report = []
    for region, rows in sorted(regions.items()):
        if len(rows) < 2:
            continue
        rows.sort(key=lambda row: row[0])
        if len({r[0] for r in rows}) != len(rows):
            raise ValueError('Ambiguous same-layer source outfit region: ' + region)
        inputs = []
        for _, node, element in rows:
            model = element.get('Model')
            inputs.append(dict(name=node.get('Name'), region=region,
                material=ET.parse(folder / element.get('Material')).getroot(),
                family={0: folder / model, **{lod: index[name] for lod, name in source_lods(index, model).items()}}))
        stem = 'outfit_' + region
        levels, material = {}, None
        source_triangles = {}
        for lod in range(max(max(g['family']) for g in inputs) + 1):
            blobs = [g['family'][min(lod, max(g['family']))].read_bytes() for g in inputs]
            canonical = canonicalize_skin_skeletons(blobs)
            garments = [dict(g, skin=blob) for g, blob in zip(inputs, canonical)]
            result = convert_fixed_outfit(garments, folder.relative_to(output).as_posix() + '/outfit_')[region]
            merge_feature_slots(result['material'])
            expected = sum(len(Skin(b).faces) for b in blobs)
            if result['triangles'] != expected:
                raise ValueError('Source triangles lost during native region assembly')
            source_triangles[lod] = expected
            if material is not None and xml(material) != xml(result['material']):
                raise ValueError('Source outfit material slots change across LODs')
            material = result['material']
            levels[lod] = result['skin']
        validate_chain(levels[0], {k: v for k, v in levels.items() if k},
                       material_slots=len(material.find('SubMaterials')))
        (folder / (stem + '.mtl')).write_bytes(xml(material))
        for lod, blob in levels.items():
            (folder / (filename(stem + '.skin', lod) if lod else stem + '.skin')).write_bytes(blob)
        _, owner, element = rows[-1]
        element.set('Model', stem + '.skin')
        element.set('Material', stem + '.mtl')
        owner.set('HidingGroups', ' '.join(sorted({group for _, node, _ in rows
                                                for group in node.get('HidingGroups', '').split()})))
        removed = {node.get('Name') for _, node, _ in rows[:-1]}
        removed_ids = {n.get('Id') for n in items if n.get('Clothing') in removed}
        for _, node, _ in rows[:-1]:
            derived.remove(node)
        for item in list(items):
            if item.get('Id') in removed_ids:
                items.remove(item)
        for item in list(preset.find('Items')):
            if item.text in removed_ids:
                preset.find('Items').remove(item)
        report.append(dict(region=region, component=owner.get('Name'),
            sources=[g['name'] for g in inputs], triangles_by_lod=source_triangles,
            policy='Source layers bundled into one regional outfit item; retained as separate material subsets'))
    return report
