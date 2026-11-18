"""Combat requests of a controller: native interrupts, and fights the combat converter owns.

KCD1 starts a quest fight by sending `combat:stimulus:customBehaviorRequest`
(`behaviorSource`, `behaviorName`, optional `entity`) to an NPC. Its combat
sub-brain stores the request in `t_customBehaviorParams` and runs
`CallBehavior Target=behaviorSource BehaviorName=behaviorName`
(`Libs/AI/final/sb_combat.xml`, `state_customBehavior`). KCD2 has no such
message and no consumer. Its form is one node per signature of
`Libs/Tables/ai/Signature.xml`:

    AddInterrupt_empty     Target Host Behavior Priority urgency ...
    AddInterrupt_wuidData  data Target Host Behavior Priority urgency ...

and the behaviour, registered on the host with `InitialState="Enabled"`,
declares `data` as a `_wuid` In parameter (`AI/quests/prepadeniVlasskehoDvora`,
`npc_archeryShoot`). So:

    target -> Target, behaviorSource -> Host, behaviorName -> Behavior,
    entity -> data, when the behaviour reads `t_customBehaviorParams.entity`
    (which becomes `data` there); a behaviour that never reads it takes the
    `empty` signature and the entity is not passed.

`Priority` and `urgency` have no KCD1 value: 161 and Fast by decision 12a
(retail `attackClosedCastle`). Every converted request is reported as a
stand-in for that reason.

A fight `campaign_combat.discover` accepts is the combat converter's: it starts
the native fight from the quest when the objective starts. The controller's
request for it, and the request that sends the partners against the fight's
actor, become `Success`, and the trees they named are `handed` (never emitted
by C2). **Inference:** the request sent with the fight's actor as `entity` is
the partners' half of that fight (the combat converter connects every partner
to the native fight).

Under an interrupt there is no combat sub-brain: a node of an interrupt
behaviour that uses `t_exitCombatSubbrain`, `t_state`, `t_fightParams`,
`t_fightOptions` or `t_fleeParams` is blocked with a reason of its own.

`AddOpponent` (KCD1: instant) has two approved stand-ins:

    Sequence[a.., AddOpponent(x), b..], outside a loop
        -> Sequence[a.., Parallel(Any, Any){AddToSkirmish(x, Hostile), Sequence[b..]}]
           (stand-in 1: the retail shape; the skirmish holds while b runs)
    AddOpponent(x) inside For / While / Loop
        -> InstantSetTarget(x) (decision 13a: sets the target only; whether a
           targeted enemy is fought is an in-game question)

`IgnoreFail="true"` keeps the second in a `SuppressFailure`; the first has no
carrier for it. One in `OnInit`, or last in its sequence, is left as written.

The registrations (`registrations` of the report) still have to be written on
the controller's template by the world side. Not runtime-verified.
"""
import re
import xml.etree.ElementTree as ET

from campaign_behavior_requests import MESSAGE, resolve
from campaign_quest_bridge import UnsupportedOperation
from quest_import import literal

SENDS = ('InstantSendMessageToNPC', 'SendMessageToNPC')
MULTI = ('InstantMultiSendMessageToNPC', 'MultiSendMessageToNPC')
FIELD = re.compile(r'\s*(\w+)\(([^()]*)\)\s*(?:,|$)')
NAME = re.compile(r"(?:[A-Za-z_]\w*|'[A-Za-z_]\w*')")
HOSTS = ('$this.id', '$__object.id')
PRIORITY, URGENCY = '161', 'Fast'
POLICY = 'Sean, 2026-11-16 (relayed by Build), decision 12a: priority 161, urgency Fast (retail attackClosedCastle)'
TARGETS = 'Sean, 2026-11-16 (relayed by Build), decision 13a; pending the in-game check that a targeted enemy is fought'
SKIRMISH = 'Sean, 2026-11-14 (relayed by the coordinator), stand-in 1'
REQUEST = 't_customBehaviorParams'
OPPONENT = re.compile(r'(\$?)\bt_customBehaviorParams\.entity\b')
SUBBRAIN = re.compile(r'\bt_(?:exitCombatSubbrain|state|fightParams|fightOptions|fleeParams|customBehaviorParams)\b')
SCRIPTS = {'code', 'onEnter', 'onExit', 'onUpdate'}
LOOPS = {'For', 'While', 'Loop'}
PARAMETER = dict(name='data', type='_wuid', values='', isPersistent='0', form='single', requirementType='In')
MANY = 'Custom combat dispatch to several targets has no native interrupt form'
STATE = 'Interrupt behaviour uses combat sub-brain state: '
# Field kinds for the behaviour compiler (campaign_controller_contracts.register adds them).
CONTRACTS = {
    'AddInterrupt_empty': dict(Target='reference', Host='reference', Behavior='string_expression', Priority='value',
                               IgnorePriorityOnPreviousInterrupt='value', urgency='value', Aliveness='value',
                               Privileged='value', FastForward='value'),
    'AddToSkirmish': dict(TargetNPC='reference', RelationOverride='value'),
    'InstantSetTarget': dict(Target='reference'),
}
CONTRACTS['AddInterrupt_wuidData'] = dict(CONTRACTS['AddInterrupt_empty'], data='reference')


def _node(op, children=(), **attributes):
    return dict(op=op, attributes={k: '"' + v + '"' for k, v in attributes.items()}, children=list(children), text='')


def _walk(node, path='Root', ancestors=()):
    yield node, path, ancestors
    for index, child in enumerate(node['children']):
        yield from _walk(child, path + '/' + str(index), ancestors + (node,))


def _request(node):
    """The request's fields, {} when they cannot be read, None when the node is not a request."""
    if node['op'] not in SENDS + MULTI or literal(node['attributes'].get('type', '')) != MESSAGE:
        return None
    text, fields, offset = literal(node['attributes'].get('values', '')), {}, 0
    while text[offset:].strip():
        match = FIELD.match(text, offset)
        if not match or match[1] in fields:
            return {}
        fields[match[1]] = match[2].strip()
        offset = match.end()
    return fields


def handed_fights(model):
    """The fights of this controller the combat converter accepts (`campaign_combat.discover`)."""
    import campaign_combat
    return [dict(tag=c['tag'], objective=c['objective'], actor=c['plan']['actor_role'], partners=c['plan']['partners'],
                 document=c['plan']['registration']['document'], tree=c['plan']['registration']['tree'],
                 outcomes={name: dict(cutscene=o['cutscene'], schedule_tag=o['schedule_tag'])
                           for name, o in sorted(c['plan']['outcomes'].items())})
            for c in campaign_combat.discover([model])['candidates']]


def _resolve(model, fields):
    """(document, tree, program) of the behaviour a request names, or a reason."""
    name = fields.get('behaviorName', '')
    if not NAME.fullmatch(name):
        return 'behaviour name is not static'
    if fields.get('behaviorSource') not in HOSTS:
        return 'behaviour source is not the controller'
    try:
        found = resolve(model, dict(source=fields['behaviorSource'], tree=name.strip("'")))
    except UnsupportedOperation as error:
        return str(error)
    return found['document'], found['tree'], found['program']


def _reads(program):
    """Members of the stored request the tree reads; '<script>' when a script names it."""
    members = set()
    for node, _, _ in _walk(program['root']):
        for attribute, raw in node['attributes'].items():
            if REQUEST in raw:
                members.update(['<script>'] if attribute in SCRIPTS
                               else re.findall(r'\bt_customBehaviorParams\b(?:\.(\w+))?', raw))
    return {member or '<whole>' for member in members}


def _opponents(tree, body, report, quest_stand_ins):
    """Rewrite the AddOpponent sites of one tree that have an approved form."""
    changed = True
    while changed:
        changed = False
        for node, path, ancestors in _walk(body['root']):
            if node['op'] != 'AddOpponent' or node.get('left'):
                continue
            who, ignore = literal(node['attributes'].get('who', '')), literal(node['attributes'].get('IgnoreFail', 'false'))
            parent = ancestors[-1] if ancestors else None
            reason = None
            if set(node['attributes']) - {'who', 'IgnoreFail', 'saveVersion'} or node['children'] or not who \
                    or ignore not in ('true', 'false'):
                reason = 'fields outside who and IgnoreFail'
            elif any(a['op'] in LOOPS for a in ancestors):
                target = _node('InstantSetTarget', Target=who)
                target.update(source_op='AddOpponent', stand_in='InstantSetTarget')
                if ignore == 'true':
                    target = dict(_node('SuppressFailure', [target]), source_op='AddOpponent', stand_in='InstantSetTarget')
                node.clear(); node.update(target)
                report['opponents'].append(dict(tree=tree, path=path, who=who, target='InstantSetTarget', approved=TARGETS))
                quest_stand_ins.append(dict(tree=tree, path=path, source='AddOpponent', target='InstantSetTarget'))
            elif any(a['op'] == 'OnInit' for a in ancestors):
                reason = 'in OnInit: the behaviour body would have to move under the skirmish'
            elif parent is None or parent['op'] != 'Sequence' or parent['children'][-1] is node:
                reason = 'not followed by the rest of a sequence'
            else:
                index = next(i for i, child in enumerate(parent['children']) if child is node)
                rest = parent['children'][index + 1:]
                skirmish = _node('Parallel', [_node('AddToSkirmish', TargetNPC=who, RelationOverride='Hostile'),
                                              _node('Sequence', rest)], successMode='Any', failureMode='Any')
                skirmish.update(source_op='AddOpponent', stand_in='AddToSkirmish')
                parent['children'][index:] = [skirmish]
                report['opponents'].append(dict(tree=tree, path=path, who=who, target='AddToSkirmish', approved=SKIRMISH,
                                                ignore_fail_dropped=ignore == 'true'))
                quest_stand_ins.append(dict(tree=tree, path=path, source='AddOpponent', target='AddToSkirmish'))
                changed = True
            if reason:
                node['left'] = reason
                report['left'].append(dict(tree=tree, path=path, operation='AddOpponent', reason=reason))
            if changed:
                break  # paths moved: walk the tree again


def apply(model, fights=()):
    """Rewrite the controller's combat requests and opponents in place; return the report.

    `fights` is `handed_fights(model)`. `stand_ins` of the report are rows for
    the conversion report's stand-in list.
    """
    own = 'libs/ai/quests/' + model['quest'].lower() + '.xml'
    trees = model['behavior_documents'].get(own, dict(trees={}))['trees']
    report = dict(quest=model['quest'], policy=dict(priority=int(PRIORITY), urgency=URGENCY, approved=POLICY),
                  handed=[], interrupts=[], registrations=[], subbrain_state=[], opponents=[], left=[], stand_ins=[],
                  runtime_verified=False)
    sites = [(tree, path, node, _request(node)) for tree, body in trees.items() for node, path, _ in _walk(body['root'])
             if _request(node) is not None]
    taken, handed_trees = set(), set()
    for fight in fights:
        row = dict(fight, trees=[fight['tree']] if fight['document'] == own else [], sites=[], converter='campaign_combat')
        actor = "$t_actors['%s']" % fight['actor']
        for tree, path, node, fields in sites:
            name = fields.get('behaviorName', '').strip("'")
            partner = fields.get('entity', '').replace('"', "'") == actor and name != fight['tag']
            if id(node) in taken or not (name == fight['tag'] or partner):
                continue
            if partner:
                found = _resolve(model, fields)
                if isinstance(found, str) or found[0] != own:
                    continue
                if found[1] not in row['trees']: row['trees'].append(found[1])
            taken.add(id(node))
            row['sites'].append(dict(tree=tree, path=path, operation=node['op'], behavior=name,
                                     role='partners' if partner else 'actor'))
            node.update(op='Success', attributes={}, source_op=node['op'], handed='campaign_combat')
        handed_trees.update(row['trees'])
        report['handed'].append(row)
    groups = {}
    for tree, path, node, fields in sites:
        if id(node) in taken or tree in handed_trees:
            continue
        found = 'several targets' if node['op'] in MULTI else 'request fields cannot be read' if not fields else (
            'fields outside behaviorSource, behaviorName, entity' if set(fields) - {'behaviorSource', 'behaviorName', 'entity'}
            else _resolve(model, fields))
        if not isinstance(found, str) and found[0] != own:
            found = 'behaviour is registered outside the controller document'
        if isinstance(found, str):
            if node['op'] in MULTI:
                node.setdefault('blocked', []).append(MANY)
            report['left'].append(dict(tree=tree, path=path, operation=node['op'], reason=found))
            continue
        groups.setdefault(found[1], dict(program=found[2], sites=[]))['sites'].append((tree, path, node, fields))
    for name in sorted(groups):
        program, requests = groups[name]['program'], groups[name]['sites']
        reads = _reads(program)
        reason = None
        if name in handed_trees:
            reason = 'behaviour is handed to the combat converter'
        elif reads - {'entity'}:
            reason = 'behaviour reads the stored request beyond its entity: ' + ', '.join(sorted(reads - {'entity'}))
        elif reads and not all('entity' in fields for _, _, _, fields in requests):
            reason = 'behaviour reads an opponent a request does not pass'
        elif reads and any(v.get('name') == 'data' for v in program['variables']):
            reason = 'behaviour has a variable named data'
        if reason:
            report['left'].extend(dict(tree=tree, path=path, operation=node['op'], reason=reason)
                                  for tree, path, node, _ in requests)
            continue
        signature = 'wuidData' if reads else 'empty'
        if reads:
            for node, _, _ in _walk(program['root']):
                for attribute, raw in node['attributes'].items():
                    node['attributes'][attribute] = OPPONENT.sub(lambda m: m[1] + 'data', raw)
            program['parameters'] = [dict(PARAMETER)]
        for node, path, _ in _walk(program['root']):
            state = sorted({m for raw in node['attributes'].values() for m in SUBBRAIN.findall(raw)})
            if state:
                node.setdefault('blocked', []).append(STATE + ', '.join(state))
                report['subbrain_state'].append(dict(tree=name, path=path, operation=node['op'], variables=state))
        behaviors = set()
        for tree, path, node, fields in requests:
            behavior = fields['behaviorName'].strip("'")
            behaviors.add(behavior)
            attributes = dict(Target=literal(node['attributes'].get('target', '')), Host=fields['behaviorSource'],
                              Behavior=behavior, Priority=PRIORITY, IgnorePriorityOnPreviousInterrupt='false',
                              urgency=URGENCY, Aliveness='Alive', Privileged='false', FastForward='false')
            if reads:
                attributes = dict(data=fields['entity'], **attributes)
            dropped = 'entity' in fields and not reads
            source = node['op']
            node.clear()
            node.update(_node('AddInterrupt_' + signature, **attributes), source_op=source, stand_in='interrupt policy',
                        requires=[(own, name)])
            report['interrupts'].append(dict(tree=tree, path=path, behavior=behavior, behavior_tree=name,
                                             signature=signature, entity_not_passed=dropped))
            report['stand_ins'].append(dict(tree=tree, path=path, source='customBehaviorRequest',
                                            target='AddInterrupt_' + signature))
        report['registrations'].extend(dict(behavior=behavior, document=own, tree=name, signature=signature,
                                            initial_state='Enabled') for behavior in sorted(behaviors))
    for tree, body in trees.items():
        if tree not in handed_trees:
            _opponents(tree, body, report, report['stand_ins'])
    for body in trees.values():
        for node, _, _ in _walk(body['root']):
            node.pop('left', None)
    return report


def declare_parameters(files, model, report):
    """Add the `data` In parameter to each emitted wuidData behaviour; return the files.

    The behaviour compiler emits `Variables` only. Retail declares a signature's
    parameters in a `Parameters` element after it.
    """
    wanted = {row['tree'] for row in report['registrations'] if row['signature'] == 'wuidData'}
    result = dict(files)
    for path, blob in files.items():
        root = ET.fromstring(blob)
        found = [tree for tree in ([root] if root.tag == 'BehaviorTree' else root.iter('BehaviorTree'))
                 if tree.get('name') in wanted and tree.find('Root') is not None]
        for tree in found:
            if tree.find('Parameters') is not None or tree.find('Variables') is None:
                raise ValueError('Interrupt behaviour cannot take its parameter: ' + tree.get('name'))
            parameters = ET.Element('Parameters')
            ET.SubElement(parameters, 'Variable', PARAMETER)
            tree.insert(list(tree).index(tree.find('Variables')) + 1, parameters)
        if found:
            result[path] = ET.tostring(root, encoding='utf-8', xml_declaration=blob.lstrip().startswith(b'<?xml'))
    return result
