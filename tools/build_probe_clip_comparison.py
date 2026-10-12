"""Build local, one-variable probe clipping cases from installed game assets.

Does not install, launch, modify the source games, or regenerate cubemaps.
The native editor fixture is an authored control, not an inferred association.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import rewrite
from upgrade_map import read, xml
from world_lighting import defaults, overlay


NATIVE_LAYER = 'Data/Levels/trosecko/Layers/main/tvid_vidlak/M01_intro/_enviro.lyr'
NATIVE_IDS = {'9f63c961-b731-46bd-9ea4-4cda5ff67b17',
              'b31b0535-06c8-4cc4-92ec-38101f58bc0b',
              'd7db80bc-a24b-4245-acdd-dae90c66aacd'}
CASES = (
    ('00_probe_off', False, False, False),
    ('01_native_unlinked', True, False, False),
    ('02_explicit_clip', True, True, False),
    ('03_explicit_clip_area_only', True, True, True),
)


def variant(root, schema, active, linked, area_only):
    root = copy.deepcopy(root)
    by_name = {e.get('Name'): e for e in root.iter('Entity')}
    upper = by_name['gm_lighting_26457']
    lower = by_name['gm_lighting_26456']
    clip = by_name['gm_lighting_8795']
    lower.find('Properties').set('bActive', '0')
    props = upper.find('Properties')
    props.set('bActive', str(int(active)))
    options = props.find('Options')
    native = schema.find('Options')
    for key in ('bIgnoresVisAreas', 'bAffectsThisAreaOnly', 'bDeferredClipBounds'):
        options.set(key, native.get(key))
    for node in list(upper.findall('EntityLinks')):
        upper.remove(node)
    if linked:
        options.set('bDeferredClipBounds', '1')
        ET.SubElement(ET.SubElement(upper, 'EntityLinks'), 'Link',
                      Name='ClipVolume', TargetId=clip.get('EntityId'),
                      TargetGuid=clip.get('EntityGuid'))
    if area_only:
        options.set('bAffectsThisAreaOnly', '1')
    return root


def schema(game):
    with zipfile.ZipFile(game/'Data/Scripts.pak') as z:
        name = next(n for n in z.namelist() if n.lower().endswith('/environmentlight.lua'))
        return defaults(read(z, name))


def build(source, target, mod, output):
    if output.exists():
        raise FileExistsError('Choose a fresh comparison directory')
    native_schema, source_schema = schema(target), schema(source)
    layer = ET.parse(target/NATIVE_LAYER).getroot()
    control = ET.Element('Layer', GUID='fd861029-d8ac-4462-9389-9a0b3a783324', HavePhysics='1', IsDefaultColor='1')
    objects = ET.SubElement(control, 'Objects')
    for obj in layer.iter('Object'):
        if obj.get('Id') in NATIVE_IDS:
            objects.append(copy.deepcopy(obj))
    if len(objects) != 3:
        raise ValueError('Native authored house/probe/clip fixture changed')
    baseline = mod/'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(baseline) as z:
        root = ET.fromstring(read(z, 'objects_mission0.xml'))
        baseline_hashes = {n: hashlib.sha256(read(z, n)).hexdigest() for n in z.namelist()}
    output.mkdir(parents=True)
    (output/'native-house-control.lyr').write_bytes(xml(control))
    (output/'kcd1-defaults.xml').write_bytes(xml(source_schema))
    (output/'kcd2-defaults.xml').write_bytes(xml(native_schema))
    source_fixture = ET.Element('Objects')
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        archive_names = {n.lower(): n for n in z.namelist()}
        src = ET.fromstring(read(z, 'objects_mission0.xml'))
        for e in src.iter('Entity'):
            if e.get('EntityId') in ('26456', '26457', '8756', '8775', '8795'):
                source_fixture.append(copy.deepcopy(e))
        for e in source_fixture:
            clip = e.find('ClipVolume')
            if clip is not None:
                name = clip.get('GeometryFileName').replace('%level%/', '')
                dest = output/'kcd1-geometry'/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(read(z, archive_names[name.lower()]))
    (output/'kcd1-house-export.xml').write_bytes(xml(source_fixture))
    if len(source_fixture) != 5:
        raise ValueError('KCD1 house fixture changed')
    native_probe = next(o for o in objects if o.get('EntityClass') == 'EnvironmentLight')
    effective = copy.deepcopy(native_schema)
    overlay(effective, native_probe.find('Properties'))
    (output/'native-house-effective-properties.xml').write_bytes(xml(effective))
    native_fixture = ET.Element('Objects')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        for name in z.namelist():
            if not name.lower().endswith('.xml'):
                continue
            blob = read(z, name)
            if b'9f63c961-b731-46bd' not in blob and b'd7db80bc-a24b-4245' not in blob:
                continue
            for e in ET.fromstring(blob).iter('Entity'):
                if e.get('EntityGuid') in ('9f63c961-b731-46bd', 'd7db80bc-a24b-4245'):
                    native_fixture.append(copy.deepcopy(e))
        if len(native_fixture) != 2:
            raise ValueError('Native editor fixture does not match exported identities')
        names = {n.lower(): n for n in z.namelist()}
        for e in native_fixture:
            clip = e.find('ClipVolume')
            if clip is not None:
                name = clip.get('GeometryFileName').replace('%level%/', '')
                dest = output/'kcd2-geometry'/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(read(z, names[name.lower()]))
    (output/'native-house-export.xml').write_bytes(xml(native_fixture))
    report = {'baseline': str(baseline), 'native_editor_layer': NATIVE_LAYER,
              'native_probe_options': effective.find('Options').attrib,
              'native_explicit_links': len(native_probe.findall('EntityLinks/Link')),
              'runtime_verified': False, 'cases': [],
              'limits': ['KCD1 fixture is a shipped level export; no KCD1 editor session was run.',
                         'Native layer control is unmodified and retains original world coordinates.',
                         'Each case requires the existing mod assets and corrected SVO tile.',
                         'Only package structure is validated; no clipping result is presumed.']}
    for name, active, linked, area in CASES:
        case = variant(root, native_schema, active, linked, area)
        dest = output/name/'Data/Levels/kcd1_travel/level.pak'
        rewrite(baseline, dest, {'objects_mission0.xml': xml(case)})
        with zipfile.ZipFile(dest) as z:
            if z.testzip() is not None:
                raise ValueError('Comparison package CRC failure')
            changed = [n for n in z.namelist() if hashlib.sha256(read(z,n)).hexdigest() != baseline_hashes[n]]
            if changed != ['objects_mission0.xml']:
                raise ValueError('Comparison altered non-entity assets: '+repr(changed))
        report['cases'].append(dict(name=name, upper_active=active, explicit_link=linked,
                                   area_only=area, changed_entries=changed))
    (output/'comparison.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'target', 'mod', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    result = build(**vars(parser.parse_args()))
    print(json.dumps(result, indent=2))
