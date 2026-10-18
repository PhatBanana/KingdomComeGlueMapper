"""Discover supported source proximity observers for packaged quest dialogues."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
from campaign_proximity_dialogue import attrs, parse, install
from campaign_sources import RetailSourceReader
from campaign_dependency_adapters import SourceTables


def upgrade(files, source):
    quests = {p:ET.fromstring(b).find('Skald/Quest') for p,b in files.items()
              if p.startswith('Quests/') and p.endswith('.xml')}
    quests = {p:h for p,h in quests.items() if h is not None}
    aliases = {d.get('Alias') for p,b in files.items() if p.startswith('Quests/') and p.endswith('.xml')
               for d in ET.fromstring(b).findall('.//Dialog/Dialogue//Decision') if d.get('Alias')}
    if not quests or not aliases: return {}, []
    registered = {s.get('soul_id') for p,b in files.items() if p.startswith('Libs/Tables/rpg/soul__')
                  for s in ET.fromstring(b).iter('soul')}
    players = {s.get('SharedSoulGuids') for p,b in files.items() if p.startswith('Quests/') and p.endswith('.xml')
               for s in ET.fromstring(b).findall("./Skald/Level/Assets/SoulAsset[@Name='player']")}
    if len(players)!=1: raise ValueError('Ambiguous proximity player binding')
    changes, report = {}, []
    with RetailSourceReader(Path(source)) as reader:
        tables = SourceTables(Path(source),reader)
        topics={r['label']:r['topic_id'] for r in tables.get('text/topic')['rows'] if r.get('label')}
        participants=tables.get('text/topictorole')['rows']; memberships=tables.get('rpg/soul2role')['rows']
        roles={r['role_id']:r for r in tables.get('rpg/role')['rows']}
        metas={r['metarole_id']:r['metarole_name'] for r in tables.get('rpg/metarole')['rows']}
        for path,host in quests.items():
            quest=host.get('Name'); controller='Libs/AI/quests/'+quest+'.xml'
            # Imported quest names retain their original source identity.
            from campaign_sources import MissingRetailSource
            try: blob=reader(Path(source),{'controller':('Scripts.pak',controller)})['controller']['data']
            except MissingRetailSource: continue
            output=files[path]
            for tree in ET.fromstring(blob).iter('BehaviorTree'):
                objectives=sorted({attrs(g).get('objectiveName') for g in tree.findall('./Root//QuestObjectiveGate')
                    if g.findall('.//DistanceGate') and g.findall('.//SendMessageToNPC')})
                if not objectives and tree.findall('./Root//DistanceGate') and any(
                        attrs(m).get('type')=='dialog:monologRequest' for m in tree.findall('./Root//SendMessageToNPC')):
                    report.append(dict(quest=quest,tree=tree.get('name'),status='unsupported',
                                       reason='Proximity speech outside a supported objective observer'))
                for objective in objectives:
                    row=dict(quest=quest,tree=tree.get('name'),objective=objective)
                    try: plan=parse(tree,objective)
                    except ValueError as error:
                        report.append(dict(row,status='unsupported',reason=str(error)));continue
                    required={lane['alias'] for lane in plan['lanes']}
                    if not required<=aliases:
                        report.append(dict(row,status='missing_dialogue',aliases=sorted(required-aliases)));continue
                    speakers=[]
                    for alias in required:
                        needed={r['role_id'] for r in participants if r['topic_id']==topics.get(alias)
                                and metas[roles[r['role_id']]['metarole_id']]=='NPC'}
                        speakers.append({r['soul_id'] for r in memberships if r['role_id'] in needed and r['soul_id'] in registered})
                    if any(len(s)!=1 for s in speakers) or len(set.union(*speakers))!=1:
                        raise ValueError('Ambiguous source proximity speaker: '+str(row))
                    speaker=next(iter(speakers[0]))
                    prefix='gm_proximity_'+hashlib.sha256((quest+'/'+tree.get('name')+'/'+objective).encode()).hexdigest()[:12]
                    current=ET.fromstring(output)
                    if current.find(".//Nodes/*[@Name='"+prefix+"_initial']") is None:
                        output=install(output,plan,speaker,next(iter(players)),prefix)
                    report.append(dict(row,status='installed',speaker=speaker,plan=plan,prefix=prefix))
            if output!=files[path]:changes[path]=output
    return changes,report
