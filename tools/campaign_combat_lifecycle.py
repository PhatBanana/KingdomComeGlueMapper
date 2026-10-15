"""Resolve ancillary combat programs without selecting a quest or an NPC.

The supported shape is deliberately strict: an optional home-tool cleanup,
then a guarded privacy change/dialogue and parallel work/proximity speech.
Unknown branching is an error, never a silently flattened list of actions.
"""
import re
from campaign_combat_plan import attrs, walk, one
from campaign_quest_bridge import UnsupportedOperation


def children(node, names):
    if [n['op'] for n in node['children']] != names:
        raise UnsupportedOperation('Unsupported lifecycle shape at ' + node['op'])
    return node['children']


def guard(node, branch):
    a = attrs(node)
    if node['op'] != 'QuestObjectiveCondition' or a['quest'] not in ('', '$__object.name'):
        raise UnsupportedOperation('Lifecycle guard needs a local quest objective')
    if a['function'] not in ('IsObjectiveCompleted', 'IsObjectiveUnchanged'):
        raise UnsupportedOperation('Unsupported lifecycle objective predicate')
    children(node, [branch])
    return dict(objective=a['objective'], function=a['function'], negate=branch == 'Else')


def preparation(root):
    calls = [n for n in walk(root) if n['op'] == 'CallBehavior' and attrs(n)['BehaviorName'] == 'cleanup']
    if not calls:
        return None
    call = one(calls, 'Multiple pre-fight tool cleanup calls')
    target = attrs(call)['Target']
    suppress = one((n for n in walk(root) if n['op'] == 'SuppressFailure' and
                    any(x is call for x in walk(n))), 'Cleanup must retain source failure suppression')
    parent = one((n for n in walk(root) if n['op'] == 'Sequence' and
                  any(c is suppress for c in n['children'])), 'Missing cleanup sequence')
    if parent['children'][0] is not suppress or len(parent['children']) < 2 or parent['children'][1]['op'] != 'ExecuteLua':
        raise UnsupportedOperation('Cleanup must precede combat health initialization')
    condition, = children(suppress, ['QuestObjectiveCondition'])
    predicate = guard(condition, 'Else')
    check, = children(condition['children'][0], ['IfCondition'])
    if attrs(check) != dict(failOnCondition='false', condition='$' + target + ' ~= $__null'):
        raise UnsupportedOperation('Unsupported tool availability test')
    sequence, = children(check, ['Sequence'])
    instant, selected = children(sequence, ['Expression', 'CallBehavior'])
    if selected is not call or re.sub(r'\s', '', attrs(instant)['expressions']) != '$t_pickInstant=true,$t_placeInstant=true,':
        raise UnsupportedOperation('Unsupported cleanup manipulation policy')
    search = one((n for n in walk(root) if n['op'] == 'GraphSearch' and any(
        c['op'] == 'SlotClassFilter' and attrs(c)['Child'] == target for c in n['children'])),
        'Missing source tool-slot search')
    slot, = children(search, ['SlotClassFilter'])
    a = attrs(slot)
    if a['Category'] or a['Source'] != 'Child' or not re.fullmatch(r'[0-9a-fA-F-]{36}', a['ClassId']):
        raise UnsupportedOperation('Unsupported cleanup item filter')
    home = one((attrs(n)['Child'] for n in walk(root) if n['op'] == 'LinkTagFilter' and attrs(n)['tag'] == 'Home'), 'Missing cleanup Home reference')
    if attrs(search)['Origin'] != home:
        raise UnsupportedOperation('Cleanup search is not rooted in source Home')
    return dict(guard=predicate, item_class=a['ClassId'], depth=int(attrs(search)['depth']),
                instant=True, optional=True, source=suppress)


def aftermath(root):
    behavior = one((n for n in root['children'] if n['op'] == 'Behavior'), 'Missing aftermath body')
    sequence, = children(behavior, ['Sequence'])
    privacy, dialogue, parallel = children(sequence, ['QuestObjectiveCondition', 'Sequence', 'Parallel'])
    privacy_guard = guard(privacy, 'Else')
    remove, = children(privacy['children'][0], ['RemoveAreaLabel'])
    if not re.fullmatch(r'[A-Za-z_]\w*', attrs(remove)['Label']):
        raise UnsupportedOperation('Unsupported dynamic area label')
    home_vars = [attrs(n)['Child'] for n in walk(root) if n['op'] == 'LinkTagFilter' and attrs(n)['tag'] == 'Home']
    if attrs(remove)['Area'] not in home_vars:
        raise UnsupportedOperation('Privacy change does not reference actor Home')
    expression, condition = children(dialogue, ['Expression', 'QuestObjectiveCondition'])
    dialogue_guard = guard(condition, 'Then')
    include, = children(condition['children'][0], ['IncludeTree'])
    if attrs(include)['Name'] != 'dialogInitiator':
        raise UnsupportedOperation('Unsupported aftermath dialogue dispatch')
    aliases = re.findall(r"\.alias\s*=\s*'([^']+)'", attrs(expression)['expressions'])
    alias = one(aliases, 'Ambiguous aftermath dialogue')
    if attrs(parallel) != dict(successMode='Any', failureMode='Any'):
        raise UnsupportedOperation('Unsupported aftermath parallel lifetime')
    loop, work = children(parallel, ['Loop', 'CallBehavior'])
    if attrs(loop)['count'] != '-1':
        raise UnsupportedOperation('Unsupported aftermath repetition')
    cycle, = children(loop, ['Sequence'])
    wait, distance = children(cycle, ['Wait', 'DistanceGate'])
    delay, radius = attrs(wait), attrs(distance)
    if (delay['timeType'] != 'GameTime' or delay['doFail'] != 'false' or delay['variation'] or
            not re.fullmatch(r'\d+(?:\.\d+)?s', delay['duration'])):
        raise UnsupportedOperation('Unsupported aftermath timer')
    if (radius['Origin'] != '' or radius['ReferencePt'] != '__player' or radius['Negation'] != 'false'
            or radius['OpenInMiddle'] != 'false' or radius['RunLogic'] != 'KeepRunning'):
        raise UnsupportedOperation('Unsupported aftermath proximity gate')
    message, = children(distance, ['InstantSendMessageToNPC'])
    a = attrs(message)
    match = re.fullmatch(r"alias\('([\w]+)'\),lookAtId\(\$__player\)", a['values'])
    if a['target'] != 'this.id' or a['type'] != 'dialog:monologRequest' or not match:
        raise UnsupportedOperation('Unsupported aftermath bark request')
    target = attrs(work)['Target']
    places = [attrs(n) for n in walk(root) if n['op'] == 'LinkDataFilter' and
              attrs(n)['tag'] == 'QuestPlace' and attrs(n)['Child'] == target]
    place = one(places, 'Missing aftermath work-place role')
    role = re.fullmatch(r"\$QuestPlace == '([\w]+)'", place['condition'])
    if not role or attrs(work)['BehaviorName'] != 'use':
        raise UnsupportedOperation('Unsupported aftermath work request')
    return dict(privacy=dict(guard=privacy_guard, label=attrs(remove)['Label']),
        dialogue=dict(guard=dialogue_guard, alias=alias), work=dict(role=role[1], behavior='use'),
        bark=dict(alias=match[1], delay=delay['duration'], low=float(radius['Low']), high=float(radius['High'])),
        source=root)
