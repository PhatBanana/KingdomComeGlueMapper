"""Standalone retail control: the same imported bandit in native Trosky."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from character_bandit_clone import resolve_template, resources, register_world
from character_person import resolve_person, native_xml, unique
from character_person_appearance import build_appearance
from region_travel_dialogue import merge_localization
from region_travel_ground import Heightfield
from region_travel_road import road_spawn_points
from region_travel_tables import managed_patches
from upgrade_map import read, xml

MOD = 'gluemapper_fritz_trosky_test'
NAME = 'gmtest_trosky_ska_fricek'


def build(source, target, output):
    source, target, output = map(Path, (source, target, output))
    if output.exists(): raise FileExistsError('Choose a fresh test build directory')
    output.mkdir(parents=True)
    person = resolve_person(source, 'ska_fricek', include_ai=False)
    template = resolve_template(target, 'tpod_bandit_3')
    directory = output/'character'
    print('Converting Fritz appearance; retaining native bandit brain and equipment', flush=True)
    character = build_appearance(source, target, person, NAME, directory)
    with zipfile.ZipFile(target/'Data/IPL_GameData.pak') as z:
        files = {'Libs/Storm/storm.xml': read(z, 'Libs/Storm/storm.xml')}
    files, names = resources(files, source, person, character, template, NAME)
    package = output/MOD
    level = package/'Data/Levels/trosecko'
    level.mkdir(parents=True)
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        candidates = []
        for path in z.namelist():
            if path == 'objects_mission0.xml' or path.startswith('layers/') and path.endswith('.xml'):
                blob = read(z, path)
                if b'tsla_nomad' in blob:
                    candidates.extend(e for e in native_xml(blob).iter('Entity') if e.get('Name') == 'tsla_nomad')
        coach = unique(candidates, 'native travel coachman')
        x,y,_ = map(float, coach.get('Pos').split(','))
        with zipfile.ZipFile(target/'Data/Levels/trosecko/terrain.pak') as terrain:
            ground = Heightfield(read(terrain, 'terrain/terrain.dat'))
        road = road_spawn_points(ground.terrain, tuple(map(float,coach.get('Pos').split(','))),
            [], ground, min_distance=80, max_distance=100, preferred_distance=90)
        px,py,_ = road['candidates'][0]['position']
        position = (px, py, ground(px,py)+.02)
        replacements = {n: read(z,n) for n in ('objects_mission0.xml', 'whdata_0',
            'tables/ai/scheduler.xml', 'waitinglinks.xml', 'triggerareas.fubar')}
        replacements, actor = register_world(replacements, source, target, template, NAME, position)
        with zipfile.ZipFile(level/'level.pak', 'x', zipfile.ZIP_STORED, allowZip64=False) as out:
            for entry in z.infolist():
                out.writestr(entry, replacements.get(entry.filename, read(z,entry.filename)))
        files[f'Mods/{MOD}/Data/Levels/trosecko/tables/ai/scheduler.xml'] = replacements['tables/ai/scheduler.xml']
    for path in directory.rglob('*'):
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            if not name.startswith('Localization/'):
                if name in files: raise ValueError('Resource collision: '+name)
                files[name] = path.read_bytes()
    files = managed_patches(files, MOD)
    with zipfile.ZipFile(package/'Data'/f'{MOD}.pak', 'x', zipfile.ZIP_STORED) as z:
        for name, blob in files.items(): z.writestr(name,blob)
    localization = package/'Localization';localization.mkdir()
    with zipfile.ZipFile(target/'Localization/English_xml.pak') as native, \
         zipfile.ZipFile(localization/'English_xml.pak','x',zipfile.ZIP_STORED) as z:
        z.writestr('text_ui_soul.xml',merge_localization(read(native,'text_ui_soul.xml'),names))
        items=directory/'Localization/English/text_ui_items.xml'
        if items.exists():z.writestr('text_ui_items.xml',merge_localization(read(native,'text_ui_items.xml'),items.read_bytes()))
    manifest = ET.Element('kcd_mod');info = ET.SubElement(manifest,'info')
    for key,value in dict(name='Fritz Trosky Bandit Test',modid=MOD,author='SamG-Coder',version='0.1.0',
        description='Standalone native-region comparison near the Trosky coachman.').items():
        ET.SubElement(info,key).text=value
    (package/'mod.manifest').write_bytes(xml(manifest))
    report = dict(mod=MOD,actor=actor,coachman=dict(coach.attrib),character=character,road=road,
        baseline='Unmodified native Trosky with the same isolated bandit clone helper',
        excludes=['KCD1 world','travel bridge','local KCD1 camp faction'],runtime_verified=False,
        files={str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob('*') if p.is_file()})
    (output/'test-build.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(package=str(package),position=position,coach=coach.get('Pos')),indent=2),flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('kcd1','kcd2','output'):p.add_argument('--'+flag,type=Path,required=True)
    a=p.parse_args();build(a.kcd1,a.kcd2,a.output)
