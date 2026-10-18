"""Preserve mandatory root-branch selection across imported forced polylogues.

The source EndTopic returns to a shared dialogue selector. Splitting that selector
into ForcedDialog nodes loses eligible higher-priority branches. Only a bounded,
unambiguous case is lowered here; rewards and objective effects remain in the
original sequences. No quest, actor, item or topic identity is selected here.
"""
import posixpath
import re
import xml.etree.ElementTree as E
from pathlib import Path

from campaign_quest_graph import xml, edge
from campaign_dialogue_effects import predicate, wire_program


def upgrade(files, source):
    if not any(p.startswith('Quests/') and p.endswith('_source_participants.xml') for p in files):
        return {}, []
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    with RetailSourceReader(Path(source)) as reader:
        tables = SourceTables(Path(source), reader)
        topics = {r['label']: r['topic_id'] for r in tables.get('text/topic')['rows'] if r.get('label')}
        branches = {r['start_topic']: r for r in tables.get('text/v_branch')['rows']}
        sequences = {r['sequence_id']: r for r in tables.get('text/sequence')['rows']}
    return lower(files, topics, branches, sequences)


def lower(files, topics, branches, sequences):
    out, report = dict(files), []
    for path, blob in files.items():
        if not path.startswith('Quests/') or not path.endswith('.xml'): continue
        root = E.fromstring(blob)
        skald = root.find('Skald')
        if skald is None or skald[0].tag not in ('Level', 'Project'): continue
        host = skald[0]; nodes = host.find('Nodes')
        if nodes is None: continue
        family = []; changed_host = False
        for definition in host.findall('Definitions/Definition'):
            dp = posixpath.normpath(posixpath.join(posixpath.dirname(path), definition.get('File')))
            if dp not in files: continue
            dr = E.fromstring(files[dp]); dialog = dr.find('Skald/ForcedDialog')
            if dialog is None: continue
            name = dialog.get('Name'); instance = nodes.find("*[@Name='"+name+"']")
            speakers = host.find("Assets/SoulAsset[@Name='"+name+"_source_participants']")
            decision = dialog.find('Dialogue/Decision')
            if instance is None or speakers is None or decision is None: continue
            tid = topics.get(decision.get('Alias')); branch = branches.get(tid, {})
            if branch.get('branch_type_id') != '0' or int(branch.get('priority', '0')) <= 0: continue
            entries = decision.findall('Sequences/Sequence')
            if len(entries) != 1: continue
            family.append(dict(path=dp, root=dr, dialog=dialog, instance=instance, name=name,
                               entry=entries[0], priority=int(branch['priority']),
                               speakers=tuple(sorted(speakers.get('SharedSoulGuids','').split()))))
        for current in family:
            candidates = [c for c in family if c['speakers']==current['speakers']
                          and c['priority'] > current['priority']]
            if not candidates: continue
            # An ambiguous family needs the complete root selector adapter.
            if len(candidates) != 1:
                report.append(dict(path=current['path'], status='pending', reason='multiple mandatory successors'))
                continue
            target = candidates[0]
            stem = current['name']+'_source_root_resume'
            if nodes.find("SceneFinishedWaiter[@Name='"+stem+"']") is not None: continue
            bindings = {e.get('To'):e.get('From') for e in current['instance'].findall('Edge')}
            entry_expression = re.sub(r"SequenceUsed\('[^']+'\)", 'false', current['entry'].get('EntryCondition',''))
            try: entry_tree = predicate(entry_expression)
            except ValueError: continue
            def negative_conjuncts(tree):
                if tree['op']=='and':
                    return sum((negative_conjuncts(c) for c in tree['children']), [])
                if tree['op']=='not' and tree['children'][0]['op']=='port':
                    return [tree['children'][0]['name']]
                return []
            negated = negative_conjuncts(entry_tree)
            # Prove the returning branch invalidates itself, avoiding loops when
            # a repeatable source question returns to the menu unchanged.
            invalidators = set()
            for p in negated:
                value = bindings.get(p, '')
                if not value.endswith('_Completed') or '.' not in value: continue
                owner, objective = value.rsplit('.', 1)
                destination = nodes.find("*[@Name='"+owner+"']")
                if destination is not None:
                    for e in destination.findall('Edge'):
                        if e.get('To') == 'complete_'+objective[:-10]:
                            prefix = current['name']+'.'
                            if e.get('From','').startswith(prefix): invalidators.add(e.get('From')[len(prefix):])
            endings = []
            for sequence in current['dialog'].findall('.//Sequence'):
                match = re.fullmatch(r'seq_(\d+)', sequence.get('Name',''))
                source = sequences.get(match[1], {}) if match else {}
                if source.get('flags')!='0' or source.get('next')!='0': continue
                if sequence.get('EndType','EndTopic')!='EndTopic': continue
                if invalidators.intersection(p.get('Name') for p in sequence.findall('Triggers/Port')):
                    endings.append(sequence)
            if not endings: continue
            expression = target['entry'].get('EntryCondition','true')
            # Native sequence history remains authoritative in the target. The
            # outer request gate only evaluates graph-readable prerequisites.
            history = re.findall(r"SequenceUsed\('([^']+)'\)", expression)
            if any(h != target['entry'].get('Name') for h in history): continue
            expression = re.sub(r"!SequenceUsed\('[^']+'\)", 'true', expression)
            try: condition = predicate(expression)
            except ValueError:
                report.append(dict(path=current['path'],status='pending',reason='non-graph successor predicate'))
                continue
            outputs = {e.get('To'):e.get('From') for e in target['instance'].findall('Edge')}
            port = 'gm_return_to_source_root'
            ports = current['dialog'].find('Ports')
            if ports.find("Port[@Name='"+port+"']") is not None: raise ValueError('Root resume port collision')
            E.SubElement(ports,'Port',Name=port,Direction='Out',Type='trigger')
            for sequence in endings:
                E.SubElement(sequence.find('Triggers'),'Port',Name=port)
            waiter = E.SubElement(nodes,'SceneFinishedWaiter',Name=stem)
            edge(waiter,current['name']+'.'+port,'Enqueue')
            wire_program(nodes,stem+'_select',stem+'.OnFinished',
                         [dict(predicate=condition,quest=target['name'],input='EnqueueDialogue')],
                         outputs,lambda *args:target['instance'])
            out[current['path']] = xml(current['root'])
            changed_host = True
            report.append(dict(path=current['path'], successor=target['path'],status='converted',
                               sequences=[e.get('Name') for e in endings],
                               source_priorities=[current['priority'],target['priority']]))
        if changed_host: out[path]=xml(root)
    return {p:b for p,b in out.items() if files.get(p)!=b}, report
