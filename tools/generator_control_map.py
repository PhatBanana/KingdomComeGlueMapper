"""Build a matched runtime control, regenerating AI rather than re-exporting it.

Terrain, navigation, geometry and character assets are deliberately held fixed.
The original editor export is the oracle, never overwritten. This tests the
minimal world-system compiler, not full terrain or KCD1 character conversion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile
import uuid

from control_world_compile import compile_world, semantic_xml
from upgrade_map import read, xml
from campaign_entity_links import native_guid


def build(reference, output, name):
    if not name.replace('_', '').isalnum(): raise ValueError('Invalid level name')
    if output.exists(): raise FileExistsError(output)
    mission_path = reference/'level.pak'
    souls = list(ET.parse(reference/'level.editor_xml').findall('WHData0/SoulList/Souls/Soul'))
    for layer in sorted((reference/'Layers').rglob('*.lyr')):
        souls.extend(ET.parse(layer).findall('WHData0/SoulList/Souls/Soul'))
    with zipfile.ZipFile(mission_path) as archive:
        mission = ET.fromstring(read(archive, 'objects_mission0.xml'))
        generated = compile_world(mission, souls, reference.name)
        parity = {n: semantic_xml(b) == semantic_xml(read(archive, n)) for n,b in generated.items()}
        if not all(parity.values()): raise ValueError('Editor parity failed: ' + repr(parity))
        generated = compile_world(mission, souls, name)
        # Sandbox starts at its camera; the standalone game requires an entity
        # registered through native SpawnPoint.lua. Derive it from that camera.
        view = ET.parse(reference/'level.editor_xml').find('View')
        spawn = ET.SubElement(mission, 'Entity', Name='ControlPlayerSpawn',
            EntityClass='SpawnPoint', Pos=view.get('ViewerPos'),
            EntityId=str(max(int(e.get('EntityId','0')) for e in mission)+1),
            EntityGuid=native_guid(int.from_bytes(uuid.uuid5(uuid.NAMESPACE_URL,name+'/spawn').bytes[:8],'little')))
        ET.SubElement(spawn,'Properties',bSaved_by_game='0',bEnabled='1',bInitialSpawn='1')
        generated['objects_mission0.xml'] = xml(mission)
        # Runtime identity changes only. Preserve the physical fixture and NPCs.
        renamed = {}
        for entry in archive.infolist():
            data = generated.get(entry.filename, read(archive, entry.filename))
            if entry.filename in ('levelinfo.xml', 'leveldata.xml'):
                data = data.replace(reference.name.encode(), name.encode())
            renamed[entry.filename] = data
        output.mkdir(parents=True)
        level = output/'Data/Levels'/name
        level.mkdir(parents=True)
        with zipfile.ZipFile(level/'level.pak', 'x', zipfile.ZIP_STORED) as target:
            for path, data in renamed.items(): target.writestr(path,data)
    for filename in ('terrain.pak','recast.pak'):
        shutil.copy2(reference/filename,level/filename)
    (level/'levelinfo.xml').write_bytes(renamed['levelinfo.xml'])
    # Native standalone table discovery also reads the loose per-level Tables.
    for path, data in renamed.items():
        if path.startswith('tables/'):
            table = level/path
            table.parent.mkdir(parents=True,exist_ok=True)
            table.write_bytes(data)
    report = dict(level=name,reference=str(reference),parity=parity,
        regenerated=list(generated),runtime_verified=False,spawn=dict(spawn.attrib),
        preserved=['objects/geometry','terrain','navigation','animation helpers','soul identity and player data'],
        scope='Minimal world-system compiler; not full KCD1 converter validation',
        reference_hash=hashlib.sha256(mission_path.read_bytes()).hexdigest(),
        files={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in output.rglob('*') if p.is_file()})
    (output/'comparison.json').write_text(json.dumps(report,indent=2))
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--name',default='fritz_generator_control')
    args=parser.parse_args()
    print(json.dumps(build(args.reference,args.output,args.name),indent=2))
