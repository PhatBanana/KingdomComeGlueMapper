"""Wire source objective predicates across converted quest instances."""
import hashlib
import xml.etree.ElementTree as ET

from campaign_dialogue_conditions import QuestConditions
from campaign_dialogue_effects import predicate, wire_program
from campaign_quest_graph import constant, edge, objective_identifier, xml
from campaign_objective_conditions import counted_asset


def expose_state_changes(blob):
    """Expose persistent source state updates for late-added controller stages."""
    root=ET.fromstring(blob);quest=root.find('./Skald/Quest')
    if quest is None:raise ValueError('State notifications require a source quest')
    ports=quest.find('Ports');output=quest.find("Nodes/Output[@Name='Output']")
    expected={s.get('Name')+'.OnExec' for s in quest.findall('Nodes/State')
        if s.get('Name') in ('quest_progress','quest_available') or s.get('Name','').startswith('objective_')}
    if not expected or ports is None or output is None:raise ValueError('Missing source quest states')
    existing=ports.findall("Port[@Name='source_state_changed']")
    if existing:
        if (len(existing)!=1 or existing[0].attrib!=dict(Name='source_state_changed',Direction='Out',Type='trigger')
                or {e.get('From') for e in output.findall("Edge[@To='source_state_changed']")}!=expected):
            raise ValueError('Conflicting source state notifications')
        return blob
    ET.SubElement(ports,'Port',Name='source_state_changed',Direction='Out',Type='trigger')
    for event in sorted(expected):edge(output,event,'source_state_changed')
    return xml(root)


def bind(files, project, models, nodes):
    roots = {m['quest']: ET.fromstring(files[project + '/' + m['quest'] + '.xml']) for m in models}
    changed = set()
    reports = []
    for model in models:
        tracked = model['tables'].get('quest_tracked_asset', {}).get('rows', [])
        for row in model['tables']['quest_objective']['rows']:
            expression = row.get('condition', '').strip()
            if not expression or expression == '1':
                continue
            if (row.get('autocomplete_timeout_str') not in ('', '-1', None)
                    or row.get('expiration_timeout_str') not in ('', '-1', None)
                    or row.get('time', '0') not in ('', '0')
                    or any(t['objective_id'] == row['objective_id'] and counted_asset(t) for t in tracked)):
                continue
            compiler = QuestConditions(models)
            try:
                tree = predicate(compiler.compile(expression))
            except ValueError:
                continue
            bindings = compiler.bindings
            if not any(b.get('quest') != model['quest'] for b in bindings.values()):
                continue
            if any(b.get('quest') not in roots or 'output' not in b for b in bindings.values()):
                continue
            for b in bindings.values():
                ports = roots[b['quest']].find('./Skald/Quest/Ports')
                if ports.find("Port[@Name='" + b['output'] + "'][@Direction='Out'][@Type='bool']") is None:
                    raise ValueError('Missing linked quest condition port: ' + str(b))
            owner = model['quest']
            name = objective_identifier(row['objective_name'])
            stem = 'linked_condition_' + hashlib.sha256((owner + ':' + row['objective_id']).encode()).hexdigest()[:20]
            timer = ET.SubElement(nodes, 'Timer', Name=stem)
            constant(timer, 'Duration', '0s'); constant(timer, 'TimeType', 'GameTime')
            dependencies = {b['quest'] for b in bindings.values()} | {owner}
            for dependency in sorted(dependencies):
                changed.add(dependency)
                edge(timer, dependency + '.source_state_changed', 'SetRunning')
            native = {key: b['quest'] + '.' + b['output'] for key, b in bindings.items()}
            native['own_started'] = owner + '.' + name + '_Started'
            guard = dict(op='and', children=[dict(op='port', name='own_started'), tree])
            instance = next(n for n in nodes if n.get('Name') == owner)
            wire_program(nodes, stem + '_apply', stem + '.OnFinished',
                         [dict(predicate=guard, quest=owner, input='complete_' + name)],
                         native, lambda *args: instance)
            reports.append(dict(quest=owner, objective=row['objective_name'], expression=expression,
                                dependencies=sorted(dependencies)))
    for name in sorted(changed):
        files[project + '/' + name + '.xml'] = expose_state_changes(xml(roots[name]))
    return reports
