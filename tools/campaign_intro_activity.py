"""Translate a selected source ground-seat/proximity-bark activity to native AI.

Selection is explicit; actor, location, bark and distances come from the source.
This adapter does not execute the rest of a quest controller or change NPC brains.
"""
import math
import re
import xml.etree.ElementTree as E

from campaign_quest_start_placement import unique
from campaign_quest_graph import xml


def normalized(blob):
    root = E.fromstring(blob)
    for tree in root.findall('BehaviorTree'):
        for child in list(tree):
            if child.tag not in ('Variables', 'Parameters', 'Root'):
                tree.remove(child)
    for n in root.iter():
        for k, v in list(n.attrib.items()):
            if len(v) >= 2 and v[0] == v[-1] == '"':
                n.set(k, v[1:-1])
    return root


def plan(blob, tree_name):
    root = normalized(blob)
    tree = unique(root.findall("BehaviorTree[@name='" + tree_name + "']"), 'intro tree')
    parallel = unique(tree.findall('.//Behavior//Parallel'), 'intro parallel')
    if parallel.get('successMode') != 'Any' or parallel.get('failureMode') != 'Any':
        raise ValueError('Unsupported intro parallel lifetime')
    gate, work = list(parallel)
    if gate.tag != 'DistanceGate' or work.tag != 'CallBehavior':
        raise ValueError('Unsupported intro activity branches')
    if (gate.get('ReferencePt') != '__player' or gate.get('Origin') != ''
            or gate.get('Negation') != 'false' or gate.get('OpenInMiddle') != 'false'
            or gate.get('RunLogic') != 'KeepRunning'):
        raise ValueError('Unsupported intro proximity semantics')
    low, high = float(gate.get('Low')), float(gate.get('High'))
    if not all(math.isfinite(v) for v in (low,high)) or not 0 <= low < high:
        raise ValueError('Invalid intro proximity bounds')
    dialog = unique(list(gate), 'intro dialogue gate')
    if (dialog.tag != 'DialogGate' or dialog.get('Who') != 'this.id'
            or dialog.get('Condition') != 'InDialog' or dialog.get('Negation') != 'true'):
        raise ValueError('Unsupported intro dialogue condition')
    seq = unique(list(dialog), 'intro bark sequence')
    message, wait = list(seq)
    match = re.fullmatch(r"alias\('([\w]+)'\),lookAtId\(\$__player\),priority\((\d+)\)", message.get('values', ''))
    if (seq.tag != 'Sequence' or message.tag != 'InstantSendMessageToNPC'
            or message.get('target') != 'this.id' or message.get('type') != 'dialog:monologRequest'
            or not match or wait.tag != 'Wait' or wait.get('duration') != '-1'
            or wait.get('doFail') != 'false'):
        raise ValueError('Unsupported intro bark lifetime')
    if work.get('BehaviorName') != 'use':
        raise ValueError('Unsupported intro work behavior')
    ref = unique((n for n in tree.iter('LinkDataFilter') if n.get('Child') == work.get('Target')),
                 'intro work binding')
    role = re.fullmatch(r"\$QuestPlace == '([\w]+)'", ref.get('condition', ''))
    if ref.get('tag') != 'QuestPlace' or not role:
        raise ValueError('Unsupported intro place role')
    requests = [n for n in root.iter('InstantSendMessageToNPC')
                if "name('" + tree_name + "')" in n.get('values', '') and n.get('type') == 'daycycle:change']
    request = unique(requests, 'intro source request')
    actor = re.fullmatch(r"\$?t_actors\['?(\w+)'?\]", request.get('target', ''))
    from campaign_behavior_schedule import source_policy
    priority, speed = source_policy(request.attrib)
    if not actor or 'once(true)' not in request.get('values', ''):
        raise ValueError('Intro requires a resolved once-only actor request')
    from campaign_intro_initialization import contract
    return dict(tree=tree_name, actor_role=actor[1], place_role=role[1], initialization=contract(tree),
                alias=match[1], bark_priority=int(match[2]), priority=priority, speed=speed,
                low=low, high=high,
                gate=dict(gate.attrib), dialog=dict(dialog.attrib), wait=dict(wait.attrib))


def emit(stem, source):
    root = E.Element('BehaviorTrees')
    tree = E.SubElement(root, 'BehaviorTree', name='intro', is_function='0')
    E.SubElement(tree, 'Variables')
    E.SubElement(E.SubElement(tree, 'Parameters'), 'Variable', name='workPlace', type='_wuid',
                 values='', form='single', isPersistent='0', requirementType='In')
    if source.get('initialization'):
        E.SubElement(tree.find('Parameters'), 'Variable', name='arrivalPlace', type='_wuid',
                     values='', form='single', isPersistent='0', requirementType='In')
    r = E.SubElement(tree, 'Root', OneTimeOnly='false', FailState='Recoverable', saveVersion='2')
    from campaign_intro_initialization import emit as initialize
    initialize(tree,r,source,stem)
    fuse = E.SubElement(E.SubElement(r, 'Behavior', canSkip='1'), 'FuseBox',
                        StatusPropagation='Child', OneCleanup='true', saveVersion='2')
    parallel = E.SubElement(E.SubElement(fuse, 'Child', canSkip='1'), 'Parallel', successMode='Any', failureMode='Any')
    gate = E.SubElement(parallel, 'DistanceGate', **dict(source['gate'], ReferencePt='$__player'))
    dialog = E.SubElement(gate, 'DialogGate', **dict(source['dialog'], Who='$this.id'))
    seq = E.SubElement(dialog, 'Sequence')
    E.SubElement(seq, 'InstantSendMessageToNPC', target='$this.id', type="'dialog:monologRequest'",
                 values=f"alias('{source['alias']}'),lookAtId($__player),priority({source['bark_priority']})")
    # Keep the source wait inside the gate: one bark per entry, no polling loop.
    E.SubElement(seq, 'Wait', duration="'-1'", timeType='GameTime', doFail='false', variation='')
    context = E.SubElement(parallel, 'EntityContextElement', context='activity_disableSchedulerLooping', enabled='true')
    E.SubElement(context, 'CallBehavior', Target='$workPlace', BehaviorName="'use'", ignoreDropUnloading='false')
    for branch, event in [('OnSuccess', 'Success'), ('OnFail', 'Fail')]:
        E.SubElement(E.SubElement(fuse, branch, canSkip='1'), 'Callback_empty', EventName=repr(event))
    E.SubElement(tree, 'EditorData', Signature=stem, EventSet='resultNotification')
    table = E.Element('database', name='barbora')
    sig = E.SubElement(E.SubElement(table, 'Signatures', version='1'), 'TreeSignature', Name=stem, EnableBehavior='true')
    E.SubElement(E.SubElement(sig, 'Parameters'), 'VariableInfo', name='workPlace', type='_wuid', form='Single',
                 values='', isOptional='false', isPersistent='false', requirementType='In')
    if source.get('initialization'):
        E.SubElement(sig.find('Parameters'), 'VariableInfo', name='arrivalPlace', type='_wuid', form='Single',
                     values='', isOptional='false', isPersistent='false', requirementType='In')
    return {'AI/' + stem + '.xml': xml(root), 'Libs/Tables/ai/Signature__' + stem + '.xml': xml(table)}
