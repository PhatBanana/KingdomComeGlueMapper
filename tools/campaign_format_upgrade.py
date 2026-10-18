"""Apply source-driven format adapters to clean builds and saved setup packages."""
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import posixpath
from upgrade_map import read


def polylogues(files, source, target):
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from campaign_polylogue import adapt, MODULE, TRIGGER
    if not any(p.startswith('Quests/') and b'<FaderDialog' in b for p,b in files.items()):
        return {}, []
    with RetailSourceReader(Path(source)) as reader:
        tables = SourceTables(Path(source), reader)
        topics = {r['label']:r['topic_id'] for r in tables.get('text/topic')['rows'] if r.get('label')}
        participants = tables.get('text/topictorole')['rows']
        memberships = tables.get('rpg/soul2role')['rows']
        roles = {r['role_id']:r for r in tables.get('rpg/role')['rows']}
        metas = {r['metarole_id']:r['metarole_name'] for r in tables.get('rpg/metarole')['rows']}
    registered = {s.get('soul_id') for p,b in files.items() if p.lower().startswith('libs/tables/rpg/soul__')
                  for s in ET.fromstring(b).iter('soul')}
    with zipfile.ZipFile(Path(target)/'Data/Scripts.pak') as native:
        templates = {p:read(native,p) for p in (MODULE,TRIGGER)}
    out = dict(files); report = []
    for path, blob in files.items():
        if not path.startswith('Quests/') or not path.endswith('.xml'): continue
        root = ET.fromstring(blob); host = root.find('./Skald/FaderDialog')
        if host is None: continue
        decision = host.find('Dialogue/Decision')
        topic = topics.get(decision.get('Alias')) if decision is not None else None
        if topic is None: continue
        needed = {r['role_id'] for r in participants if r['topic_id']==topic
                  and metas[roles[r['role_id']]['metarole_id']]=='NPC'}
        if len(needed)<2: continue
        resolved=[]
        for rid in needed:
            matches={r['soul_id'] for r in memberships if r['role_id']==rid and r['soul_id'] in registered}
            if len(matches)!=1: raise ValueError('Missing or ambiguous imported dialogue participant: '+rid)
            resolved.extend(matches)
        containers=[]
        for p,b in files.items():
            if not p.startswith('Quests/') or not p.endswith('.xml'):continue
            h=ET.fromstring(b).find('Skald')
            if h is None or h[0].tag not in ('Project','Level'):continue
            if any(posixpath.normpath(posixpath.join(posixpath.dirname(p),d.get('File')))==path
                   for d in h[0].findall('Definitions/Definition')):containers.append(p)
        if len(containers)!=1: raise ValueError('Ambiguous dialogue container: '+path)
        out, changed = adapt(out, containers[0], path, resolved, templates)
        if changed: report.append(dict(path=path, source_topic=topic, participants=sorted(resolved)))
    return {p:b for p,b in out.items() if files.get(p)!=b}, report
