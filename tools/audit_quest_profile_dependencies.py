"""Compare source quest/profile dependency closure with an installed development mod.

Source ownership limits discovery, not execution. Unowned branches and explicit
cross-quest calls remain visible. Presence checks do not prove in-game behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables
from campaign_dialogue import TABLES
from campaign_quest_dialogues import discover, scope_to_quest, import_participants
from campaign_profile_actors import collect
from upgrade_map import read


def audit(a):
    if a.output.exists():
        raise FileExistsError('Choose a fresh dependency report')
    model = json.loads(a.model.read_text(encoding='utf-8'))
    with zipfile.ZipFile(a.source / 'Data/Levels' / a.source_level / 'level.pak') as archive:
        profiles, souls = (ET.fromstring(read(archive,n)) for n in ('whdata_1','whdata_0'))
        documents = {n:read(archive,n) for n in archive.namelist()
                     if n.replace('\\','/').lower().startswith('layers/') and n.lower().endswith('.xml')}
        actors = collect(profiles, souls, documents, a.profile)
    with zipfile.ZipFile(a.mod / 'Data/gluemappertravel.pak') as archive:
        installed_souls = {row.get('soul_id') for n in archive.namelist()
            if n.lower().startswith('libs/tables/rpg/soul') and n.lower().endswith('.xml')
            for row in ET.fromstring(read(archive,n)).iter('soul')}
    with zipfile.ZipFile(a.mod / 'Data/Levels' / a.level / 'level.pak') as archive:
        mission = ET.fromstring(read(archive,'objects_mission0.xml'))
        installed_instances = {s.findtext('Guid') for s in
            ET.fromstring(read(archive,'whdata_0')).findall('./SoulList/Souls/Soul')
            if any(e.get('EntityGuid') == s.findtext('EntityGuid') for e in mission)}
    for actor in actors:
        actor['installed_soul'] = actor['soul_id'] in installed_souls
        actor['installed_instance'] = actor['instance_id'] in installed_instances
    class Requests:
        def __init__(self): self.sites = {}
        def ensure(self, kind, identity, site):
            self.sites.setdefault(identity, []).append(site)
            return identity if identity in installed_souls else None
    requests = Requests()
    with RetailSourceReader(a.source) as reader:
        source_tables = SourceTables(a.source, reader)
        tables = {n:source_tables.get('text/'+n)['rows']
                  for n in (*TABLES,'dialogue_functions','v_topic2subchapter_id')}
        closure = scope_to_quest(discover(tables,model['quest_id'],model['quest'],model),
            tables,source_tables.get('quest/quest2skald_subchapter')['rows'])
        imported = import_participants(closure,tables,source_tables,requests,
            eligible_souls={actor['soul_id'] for actor in actors})
        provenance = {n:record['provenance'] for n,record in source_tables.cache.items()}
    report = dict(quest=model['quest'], profiles=a.profile, actors=actors, dialogue_closure=closure,
        dialogue_actor_dependencies=[dict(soul_id=s,installed=imported[s] is not None,sites=sites)
                                     for s,sites in sorted(requests.sites.items())],
        provenance=provenance, model_sha256=hashlib.sha256(a.model.read_bytes()).hexdigest(),
        runtime_verified=False, profile_activation_changed=False)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(actors=len(actors), missing_instances=sum(not r['installed_instance'] for r in actors),
        dialogue_branches=len(closure['branches']), report=str(a.output))))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source','mod','model','output'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--profile',action='append',required=True)
    p.add_argument('--source-level',default='rataje')
    p.add_argument('--level',default='kcd1_travel')
    audit(p.parse_args())
