"""Resolve quest-item recovery storage and lower literal dialogue handovers.

Supports unique source owners and linear, non-cyclic ownership chains. Missing
holders or unsupported control flow are conversion errors, never ordinary moves.
"""
import hashlib
import json
import posixpath
import re
import xml.etree.ElementTree as E

from campaign_entity_links import append_links
from campaign_quest_graph import constant, edge
from upgrade_map import xml

PREFIX = 'gm_managed_quest_'
MANIFEST = 'Libs/GlueMapper/quest_item_holders.json'
CALL = re.compile(r'''\s*(?:ItemUtils|Utils)\.GiveItem\s*\(\s*([\w.]+)\s*,\s*([\w.]+)\s*,\s*['"]([\w-]+)['"]\s*,\s*(\d+)\s*\)\s*;?\s*''')


def recovery(source_objects, objects, project_name):
    targets = {l.get('TargetGuid','').upper() for l in source_objects.iter('Link')
               if l.get('Name') == 'worldStash[kind($enum:worldStashKind.lostQuestibleItems)]'}
    source = [e for e in source_objects.iter('Entity') if e.get('EntityGuid','').upper() in targets]
    if len(source) != 1 or source[0].get('EntityClass') != 'Stash':
        raise ValueError('Quest-item backup dependency: missing or ambiguous source lostQuestibleItems stash')
    converted = [e for e in objects.iter('Entity') if e.get('Name') == 'gm_container_'+source[0].get('EntityId')]
    holders = [e for e in objects.iter('Entity') if e.get('Name') == project_name]
    if len(converted) != 1 or converted[0].get('EntityClass') != 'Stash':
        raise ValueError('Quest-item backup dependency: converted Stash missing for source '+source[0].get('EntityId'))
    if len(holders) != 1:
        raise ValueError('Quest-item backup dependency: project holder missing or ambiguous')
    stash = converted[0]
    if stash.get('Layer') or stash.get('HiddenInGame') == '1':
        raise ValueError('Quest-item backup dependency: recovery stash is conditional or hidden')
    return stash, holders[0]


def chain(owner, transfers):
    result, seen = [], {owner}
    remaining = list(transfers)
    while remaining:
        candidates = [t for t in remaining if t['source'] == owner]
        if len(candidates) != 1:
            raise ValueError('Quest-item handover requires a unique connected ownership chain')
        t = candidates[0]
        if t['target'] in seen:
            raise ValueError('Cyclic quest-item handover requires a lifecycle adapter')
        result.append(t); remaining.remove(t); owner = t['target']; seen.add(owner)
    return result


def lower(files, project, active, actors, role_souls, source_objects, objects_blob, waiting_blob, quest_ids=()):
    files = dict(files)
    previous = json.loads(files[MANIFEST]) if MANIFEST in files else {}
    roots = {p:E.fromstring(b) for p,b in files.items() if p.startswith('Quests/') and p.endswith('.xml')}
    original_xml = {p:xml(r) for p,r in roots.items()}
    # Restore source scripts before rebuilding so upgrades remain idempotent.
    for saved in previous.get('scripts', []):
        seq = roots[saved['path']].find(".//Sequence[@Name='"+saved['sequence']+"']")
        if seq is None: raise ValueError('Managed quest handover source sequence disappeared')
        if seq.get('ExitScript','') not in (saved['lowered'], saved['original']):
            raise ValueError('Managed quest handover script changed outside its adapter')
        seq.set('ExitScript', saved['original'])
    for root in roots.values():
        for parent in root.iter():
            for node in list(parent):
                if node.get('Name','').startswith(PREFIX) or node.get('To','').startswith(PREFIX):
                    parent.remove(node)
    ph = roots[project].find('./Skald/Project')
    nodes, assets = ph.find('Nodes'), ph.find('Assets')
    # Remove the rejected pre-release CreateItems experiment.
    for parent in (nodes, assets):
        for n in list(parent):
            if n.get('Name','').startswith('gm_source_quest_inventory_'): parent.remove(n)
    owners = {}
    for actor in actors:
        for row in actor['items']:
            item = row['item_id']
            if item in owners: raise ValueError('Ambiguous initial owner for quest item '+item)
            owners[item] = (actor['soul'], row)
    lifecycle = {}
    item_call = re.compile(r"\s*Utils\.(CreateInvItem|RemoveInvItem)\s*\(\s*([\w.]+)\s*,\s*['\"]([\w-]+)['\"]\s*\)\s*;?\s*")
    for root in roots.values():
        for seq in root.iter('Sequence'):
            for line in seq.get('ExitScript','').splitlines():
                call = item_call.fullmatch(line)
                if call and call[1] == 'CreateInvItem' and call[3] in quest_ids:
                    if call[3] in owners:
                        raise ValueError('Quest item has both initial inventory and scripted creation: '+call[3])
                    if call[2] not in role_souls:
                        raise ValueError('Unresolved quest-item creation holder: '+call[2])
                    owner = role_souls[call[2]]
                    record = lifecycle.setdefault(call[3], dict(owner=owner, create=[], remove=[]))
                    if record['owner'] != owner:
                        raise ValueError('Multiple scripted creation holders for quest item '+call[3])
    if not owners and not lifecycle: return {}, {}, dict(items=[], scripts=[])
    objects = E.fromstring(objects_blob)
    stash, holder = recovery(source_objects, objects, ph.get('Name'))
    backup = PREFIX+'backup'
    E.SubElement(assets,'StashAsset',Name=backup)
    label = "asset['"+backup+"']"
    links = holder.find('EntityLinks')
    if links is None: links = E.SubElement(holder,'EntityLinks')
    existing = [l for l in links if l.get('Name')==label]
    if existing and any(l.get('TargetGuid')!=stash.get('EntityGuid') for l in existing):
        raise ValueError('Conflicting quest-item backup binding')
    if not existing: E.SubElement(links,'Link',Name=label,TargetGuid=stash.get('EntityGuid'),TargetId=stash.get('EntityId'))
    waiting = append_links(waiting_blob,[(holder.get('EntityGuid'),stash.get('EntityGuid'),label)])
    parents = {}
    for path,root in roots.items():
        sk = root.find('Skald')
        if sk is None: continue
        host = sk[0]
        for d in host.findall('Definitions/Definition'):
            child = posixpath.normpath(posixpath.join(posixpath.dirname(path),d.get('File')))
            if child not in roots: continue
            name = roots[child].find('Skald')[0].get('Name')
            instances = [n for n in host.findall('Nodes/*') if n.tag==name]
            if len(instances)==1:
                parents.setdefault(child,[]).append((path,instances[0].get('Name')))
    def expose(path, port):
        if path==project: return port
        if len(parents.get(path,[]))!=1: raise ValueError('Unresolved quest handover graph parent: '+path)
        parent,instance = parents[path][0]
        if parent==project: return instance+'.'+port
        host=roots[parent].find('Skald')[0]
        E.SubElement(host.find('Ports'),'Port',Name=port,Direction='Out',Type='trigger')
        out=host.find('Nodes/Output')
        if out is None: out=E.SubElement(host.find('Nodes'),'Output',Name='Output')
        edge(out,instance+'.'+port,port)
        return expose(parent,port)
    transfers={i:[] for i in owners}; scripts=[]
    for path,root in roots.items():
        for seq in root.iter('Sequence'):
            original=seq.get('ExitScript',''); lines=original.splitlines(keepends=True); lowered=[]
            for line in lines:
                match=CALL.fullmatch(line)
                if line.lstrip().startswith('--'):
                    lowered.append(line); continue
                item_match = item_call.fullmatch(line)
                if item_match and item_match[3] in lifecycle:
                    operation, who, item = item_match.groups()
                    if role_souls.get(who) != lifecycle[item]['owner']:
                        raise ValueError('Unresolved or different quest-item lifecycle holder: '+who)
                    port=PREFIX+hashlib.sha256((path+seq.get('Name')+item+operation).encode()).hexdigest()[:20]
                    dialog=root.find('Skald')[0]
                    E.SubElement(dialog.find('Ports'),'Port',Name=port,Direction='Out',Type='trigger')
                    triggers=seq.find('Triggers')
                    if triggers is None: triggers=E.SubElement(seq,'Triggers')
                    E.SubElement(triggers,'Port',Name=port)
                    lifecycle[item]['create' if operation=='CreateInvItem' else 'remove'].append(expose(path,port))
                    continue
                relevant=any(i in line for i in set(owners)|set(lifecycle))
                if not match or match[3] not in owners:
                    if relevant and any(api in line for api in ('GiveItem','RemoveInvItem','CreateInvItem')):
                        raise ValueError('Unsupported quest-item script control flow: '+path+'/'+seq.get('Name',''))
                    lowered.append(line); continue
                src,dst,item,amount=match.groups()
                if amount!='1': raise ValueError('Managed quest item transfer must be singular: '+item)
                if src not in role_souls or dst not in role_souls:
                    raise ValueError('Unresolved quest-item dialogue role: '+src+' -> '+dst)
                port=PREFIX+hashlib.sha256((path+seq.get('Name')+item).encode()).hexdigest()[:20]
                dialog=root.find('Skald')[0]
                E.SubElement(dialog.find('Ports'),'Port',Name=port,Direction='Out',Type='trigger')
                triggers=seq.find('Triggers')
                if triggers is None: triggers=E.SubElement(seq,'Triggers')
                E.SubElement(triggers,'Port',Name=port)
                transfers[item].append(dict(source=role_souls[src],target=role_souls[dst],event=expose(path,port),port=port))
            updated=''.join(lowered)
            if updated!=original:
                seq.set('ExitScript',updated)
                scripts.append(dict(path=path,sequence=seq.get('Name'),original=original,lowered=updated))
    def boolean(name, method, inputs):
        n=E.SubElement(nodes,'Function',Name=name,MethodName='math::boolean::'+method,DeclaringType='math::boolean')
        for p,v in inputs: edge(n,v,p)
        return name+'.bool'
    report=[]
    for item,(owner,row) in sorted(owners.items()):
        ordered=chain(owner,transfers[item]); stem=PREFIX+item.replace('-','_')
        holders=[owner]+[t['target'] for t in ordered]
        for t in ordered:
            n=E.SubElement(nodes,'State',Name=t['port'],TypeT='bool')
            constant(n,'DefaultValue','false');edge(n,t['event'],'SetTrue')
        for index,soul in enumerate(holders):
            name=stem+'_'+str(index)
            E.SubElement(assets,'SoulAsset',Name=name,SharedSoulGuids=soul)
            condition=active if index==0 else ordered[index-1]['port']+'.State'
            if index<len(ordered):
                neg=boolean(name+'_not_next','Not',[('Value',ordered[index]['port']+'.State')])
                condition=boolean(name+'_active','And',[('A',condition),('B',neg)])
            n=E.SubElement(nodes,'AddQuestItem',Name=name+'_item')
            constant(n,'ItemClassGUID',item);constant(n,'Health',row.get('health') or '1')
            E.SubElement(n,'Asset',Name='StartingLocation',Alias=name)
            E.SubElement(n,'Asset',Name='BackupLocation',Alias=backup)
            edge(n,condition,'IsActive')
        report.append(dict(item=item,holders=holders,transfers=len(ordered),quantity_policy='native unique quest item',
                           source_amount=row.get('amount'),source_random_add=row.get('amount_random_add')))
    for item, record in sorted(lifecycle.items()):
        name=PREFIX+item.replace('-','_')+'_created'
        state=E.SubElement(nodes,'State',Name=name,TypeT='bool')
        constant(state,'DefaultValue','false')
        for event in sorted(set(record['create'])): edge(state,event,'SetTrue')
        for event in sorted(set(record['remove'])): edge(state,event,'SetFalse')
        E.SubElement(assets,'SoulAsset',Name=name,SharedSoulGuids=record['owner'])
        condition=boolean(name+'_active','And',[('A',active),('B',name+'.State')])
        effect=E.SubElement(nodes,'AddQuestItem',Name=name+'_item')
        constant(effect,'ItemClassGUID',item)
        E.SubElement(effect,'Asset',Name='StartingLocation',Alias=name)
        E.SubElement(effect,'Asset',Name='BackupLocation',Alias=backup)
        edge(effect,condition,'IsActive')
        report.append(dict(item=item,holders=[record['owner']],creation_events=len(record['create']),
                           removal_events=len(record['remove']),quantity_policy='native unique quest item'))
    manifest=dict(items=report,scripts=scripts,backup=stash.get('EntityGuid'),runtime_verified=False)
    changes={p:xml(r) for p,r in roots.items() if xml(r)!=original_xml[p]}
    changes[MANIFEST]=json.dumps(manifest,sort_keys=True,indent=2).encode()
    return changes, {'objects_mission0.xml':xml(objects),'waitinglinks.xml':waiting}, manifest
