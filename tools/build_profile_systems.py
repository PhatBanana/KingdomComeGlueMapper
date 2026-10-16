"""Stage reusable profile population services against an existing conversion.

Keeps installed quest/combat assets as the baseline. This is a dependency and
service stage, not a claim that incomplete work programs are ready to install.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables
from campaign_profile_actors import collect
from character_person_ai import capture_person_ai, register_factions, native_brain_and_class, index_person_links
from character_schedule import plan
from character_crime_districts import discover, convert
from build_horse_trader_test import rewrite
from upgrade_map import read, xml


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def select_people(roster, names):
    """Restrict an integration slice without changing any actor's source data."""
    if not names:
        return roster
    requested = set(names)
    selected = [row for row in roster if row['name'] in requested]
    counts = Counter(row['name'] for row in selected)
    invalid = sorted(name for name in requested if counts[name] != 1)
    if invalid:
        raise ValueError('Missing or ambiguous requested profile actors: ' + ', '.join(invalid))
    return selected


def source_world(archive):
    documents = {n: read(archive,n) for n in archive.namelist()
                 if n.replace('\\','/').lower()=='objects_mission0.xml' or
                 n.replace('\\','/').lower().startswith('layers/') and n.lower().endswith('.xml')}
    entities = [e for blob in documents.values() for e in ET.fromstring(blob).iter('Entity')]
    return documents, entities


def build(a):
    if a.output.exists():raise FileExistsError('Choose a fresh systems stage')
    with zipfile.ZipFile(a.source/'Data/Levels'/a.source_level/'level.pak') as z:
        documents,entities=source_world(z)
        souls=ET.fromstring(read(z,'whdata_0'))
        roster=collect(ET.fromstring(read(z,'whdata_1')),souls,documents,a.profile)
        roster=select_people(roster,getattr(a,'person',None))
    byguid={e.get('EntityGuid'):e for e in entities if e.get('EntityGuid')}
    person_link_index=index_person_links(entities)
    instances={s.findtext('Guid'):s for s in souls.findall('SoulList/Souls/Soul')}
    travel=a.mod/'Data/gluemappertravel.pak';level=a.mod/'Data/Levels'/a.level/'level.pak'
    with zipfile.ZipFile(travel) as z:
        resources={n:read(z,n) for n in z.namelist() if n.startswith('Libs/Tables/rpg/') and n.endswith('.xml')}
    with zipfile.ZipFile(level) as z:
        files={n:read(z,n) for n in ('objects_mission0.xml','triggerareas.fubar','waitinglinks.xml')}
    original_resources = resources.copy()
    original_files = files.copy()
    with zipfile.ZipFile(a.target/'Data/Tables.pak') as z:
        brains=ET.fromstring(read(z,'Libs/Tables/ai/brain.xml'))
        classes=ET.fromstring(read(z,'Libs/Tables/rpg/social_class.xml'))
        template=ET.fromstring(read(z,'Libs/Tables/ai/smartEntity/SmartEntity__sa_crime_district.xml')).find('.//SmartEntityTemplate')
    records=[]; changes=[]
    with RetailSourceReader(a.source) as reader:
        tables=SourceTables(a.source,reader)
        for row in roster:
            soul=tables.row('rpg/soul','soul_id',row['soul_id'])
            actor=byguid[row['entity_guid']]
            ai=capture_person_ai(tables,soul,actor,instances[row['instance_id']],entities,
                                link_index=person_link_index)
            record=dict(actor=row,source_social_class=ai['source_social_class'],
                source_faction=ai['faction_graph']['faction'],source_superfaction=ai['faction_graph']['superfaction'],
                source_links=ai['links'])
            try:record['schedule']=plan(dict(name=row['name'],ai=ai),tables)
            except ValueError as error:record['schedule_error']=str(error)
            faction=register_factions(resources,ai)
            try:brain,social=native_brain_and_class(ai,brains,classes)
            except ValueError as error:
                record['person_contract_error']=str(error);records.append(record);continue
            record['native_brain']=brain;record['native_social_class']=social
            matches=[]
            for path,blob in list(resources.items()):
                if not path.lower().split('/')[-1].startswith('soul'):continue
                doc=ET.fromstring(blob)
                found=[s for s in doc.iter('soul') if s.get('soul_id')==row['soul_id']]
                for s in found:
                    before={k:s.get(k) for k in ('brain_id','social_class_id','factionName')}
                    s.set('brain_id',brain);s.set('social_class_id',social);s.set('factionName',faction)
                    after={k:s.get(k) for k in before}
                    if before!=after:
                        resources[path]=xml(doc);changes.append(dict(person=row['name'],path=path,before=before,after=after))
                    matches.append(path)
            if len(matches)>1:raise ValueError('Duplicate destination soul: '+row['name'])
            record['registered_soul_files']=matches
            records.append(record)
        root,districts=discover(entities,tables,[tuple(map(float,r['transform']['Pos'].split(','))) for r in roster])
        files,crime=convert(files,entities,root,districts,template)
        provenance={k:v['provenance'] for k,v in tables.cache.items()}
    summary=dict(profiles=a.profile,selected_people=getattr(a,'person',None),actors=len(roster),profile_counts=dict(Counter(p for r in roster for p in r['profiles'])),
        registered_souls=sum(bool(r.get('registered_soul_files')) for r in records),
        resolved_intervals=sum(len(r.get('schedule',{}).get('resolved',[])) for r in records),
        pending_intervals=sum(len(r.get('schedule',{}).get('pending',[])) for r in records),
        schedule_errors=sum('schedule_error' in r for r in records),
        person_contract_errors=sum('person_contract_error' in r for r in records),
        social_class_changes=changes,crime=crime,installed=False,runtime_verified=False,
        ready_to_install=False,
        remaining=['complete work programs and equipment','quest-controlled assignments and profile activation',
                   'crime storage, punishment and arrest conversations','location/reputation UI bindings'],
        source_tables=provenance,
        baseline={str(p):file_hash(p) for p in (travel,level)})
    a.output.mkdir(parents=True)
    (a.output/'actor-systems.json').write_text(json.dumps(records,indent=2),encoding='utf8')
    (a.output/'systems.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    # Reports/fragments are sufficient for iteration. Full package output is
    # opt-in, avoiding another copy of the mod for every audit pass.
    if getattr(a, 'package', False):
        package=a.output/'package'
        rewrite(travel,package/'Data/gluemappertravel.pak',resources)
        rewrite(level,package/'Data/Levels'/a.level/'level.pak',files)
    else:
        changed = {k:v for k,v in resources.items() if original_resources.get(k) != v}
        changed.update({'world/'+k:v for k,v in files.items() if original_files.get(k) != v})
        for path,blob in changed.items():
            dest=a.output/'fragments'/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(blob)
    return {k:v for k,v in summary.items() if k in ('actors','registered_souls','resolved_intervals','pending_intervals','schedule_errors','person_contract_errors','ready_to_install')}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--profile',action='append',required=True)
    p.add_argument('--person',action='append',help='Limit an integration slice to named source actors; repeat for each actor')
    p.add_argument('--package',action='store_true',help='Produce install packages instead of small review fragments')
    p.add_argument('--source-level',default='rataje');p.add_argument('--level',default='kcd1_travel')
    print(json.dumps(build(p.parse_args())))
