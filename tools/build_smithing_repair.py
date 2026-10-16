"""Repair native Rattay forge coal links and a missing workpiece material alias."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from upgrade_map import read, xml

MATERIAL='Objects/characters/assets/blacksmithing/blacksmithing_short_sword.mtl'
ALIAS=MATERIAL.replace('.mtl','1.mtl')
COAL_ID='c541402d-0ee9-4457-9be5-3159be42b203'


def repair_coal(blob):
    root=ET.fromstring(blob)
    by_name={e.get('Name'):e for e in root}
    for station in ('62317','62236'):
        prefix=f'gm_rattay_smith_{station}_'
        smith=by_name[prefix+'46192'];coal=by_name[prefix+'prop_'+COAL_ID]
        if not coal.get('Geometry','').lower().endswith('/coal_forge_small_a.cgf'):
            raise ValueError('Unexpected forge coal geometry')
        links=smith.find('EntityLinks')
        existing=links.findall("Link[@Name='forgeCoal']")
        if len(existing)>1:raise ValueError('Duplicate forge coal links')
        link=existing[0] if existing else ET.SubElement(links,'Link',Name='forgeCoal')
        link.set('TargetId',coal.get('EntityId'));link.set('TargetGuid',coal.get('EntityGuid'))
    return xml(root)


def build(game,mod,output):
    if output.exists():raise FileExistsError(output)
    level='Data/Levels/kcd1_travel/level.pak';travel='Data/gluemappertravel.pak'
    with zipfile.ZipFile(mod/level) as z:
        mission=repair_coal(read(z,'objects_mission0.xml'))
    with zipfile.ZipFile(game/'Data/IPL_Characters-part0.pak') as z:
        material=read(z,MATERIAL)
    # The four native .skin files embed the trailing-1 name. Use an exact
    # material alias in the same directory so all relative textures still work.
    with zipfile.ZipFile(game/'Data/Characters.pak') as z:
        for suffix in ('','_hot_01','_hot_02','_hot_03'):
            name=MATERIAL.replace('.mtl',suffix+'.skin')
            if b'blacksmithing_short_sword1\0' not in read(z,name):
                raise ValueError('Native skin material reference changed: '+name)
    changes={level:{'objects_mission0.xml':mission},travel:{ALIAS:material}}
    report=dict(installed=False,runtime_verified=False,baseline={},packages={})
    for rel,replacements in changes.items():
        report['baseline'][rel]=digest(mod/rel)
        target=output/'package'/rel;rewrite(mod/rel,target,replacements)
        with zipfile.ZipFile(mod/rel) as a,zipfile.ZipFile(target) as b:
            assert {i.filename:(i.CRC,i.file_size) for i in a.infolist() if i.filename not in replacements}=={i.filename:(i.CRC,i.file_size) for i in b.infolist() if i.filename not in replacements}
            assert all(read(b,n)==v for n,v in replacements.items())
        report['packages'][rel]=digest(target)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('game','mod','output'):p.add_argument('--'+key,type=Path,required=True)
    build(**vars(p.parse_args()))
