"""The controller's half of the scene seam (C2 side of C5).

KCD1 plays a scene through library code inside the quest controller: a tree
sends itself a `cutscene` request, the entry tree's `cutsceneAutomaton`
(final/questUtils.xml) plays it and then includes `cutscene_<alias>` from the
quest's own file, and finally starts and completes the request's save
objective. In the port the scene converter (C5, module `gm_<quest>_scenes`)
owns playback. For the aliases it owns, this module rewrites the controller:

    request     InstantSendMessageToNPC type=cutscene alias('x')  ->  a signal
                that fires the module's In trigger `play_x`
    automaton   IncludeTree cutsceneAutomaton  ->  IncludeTree of a generated
                dispatcher in the quest's own file. Per alias it waits for the
                module's Out bool `pending_x`, includes `cutscene_x`, runs the
                request's save objective exactly as the automaton does, fires
                the module's In trigger `done_x` and waits for `pending_x` to
                clear.

`pending_x` and `done_x` are the seam's requirement on C5: a bool that is true
from the moment the scene ends (completed or skipped) until the controller
acknowledges. Playback fields of the request (fades, sound, combat) stay
C5's; a field that changes what the controller must run (begin and
finalisation events, overrides, chained scenes) leaves the alias unconverted.
The automaton's other work around playback (save lock, fader, player locks,
actor restrictions, clothes, teleports) is C5's playback policy and is listed
in the report as handed over, not dropped silently.

Nothing connects the bridge ports to the module yet; the report carries the
wiring to make. Not runtime-verified.
"""
import re
import xml.etree.ElementTree as ET

MESSAGE = 'cutscene'
AUTOMATON = 'cutsceneAutomaton'
# Request fields: what the controller does with them.
CONTROLLER_FIELDS = {'alias', 'state', 'saveGameQuest', 'saveGameObjective'}
PLAYBACK_FIELDS = {'customFadeIn', 'dialogFadeIn', 'postFinalizationCustomFadeIn', 'postFinalizationDialogFadeIn',
                   'holsterWeapon', 'keepHalberd', 'freezeAI', 'time', 'weather', 'muteSounds', 'preventCombat',
                   'customFadeInIsFromCombat', 'preteleportPlayer', 'disableReadinessWait', 'disableSun',
                   'suspendBattleContext', 'battleType'}
HANDED_TO_PLAYBACK = ('save lock while the scene runs', 'fader and sound mute', 'player-not-in-scene lock',
                      'dropping a carried body', 'combat prevention and its buffs', 'player pre-teleport',
                      'actor restrictions and scene clothes', 'time of day', 'scene subscriptions',
                      'actor teleports and readiness wait', 'post-scene fade-in')
SELF = ('this.id', '$this.id', '__object.id', '$__object.id')


def module_name(quest):
    return 'gm_' + quest + '_scenes'


def dispatcher_name(quest):
    return quest + '_scene_dispatch'


def _text(node, name):
    raw = node['attributes'].get(name, '')
    return raw[1:-1] if len(raw) >= 2 and raw[0] == raw[-1] == '"' else raw


def _node(op, children=(), **attributes):
    return dict(op=op, attributes=dict(attributes), children=list(children), text='')


def _walk(node, path='Root'):
    yield node, path
    for index, child in enumerate(node['children']):
        yield from _walk(child, path + '/' + str(index))


def fields(values):
    """Parse `name(value), ...`; None when the text is anything else."""
    result, offset = {}, 0
    pattern = re.compile(r"\s*(\w+)\s*\(\s*('[^'\r\n]*'|[^(),'\r\n]+)\s*\)\s*(?:,|$)")
    while values[offset:].strip():
        match = pattern.match(values, offset)
        if not match or match[1] in result:
            return None
        result[match[1]] = match[2].strip()
        offset = match.end()
    return result


def requests(model):
    own = model['behavior_documents'].get('libs/ai/quests/' + model['quest'].lower() + '.xml', dict(trees={}))
    for tree, body in own['trees'].items():
        for node, path in _walk(body['root']):
            if node['op'] in ('InstantSendMessageToNPC', 'SendMessageToNPC') and _text(node, 'type') == MESSAGE:
                yield tree, path, node


def plan(model, owned):
    """Return ({alias: save or None}, report) for the owned aliases the controller can serve."""
    own = model['behavior_documents'].get('libs/ai/quests/' + model['quest'].lower() + '.xml', dict(trees={}))
    entries = [e['tree'] for e in (model.get('controller_registration') or {}).get('entry_points', [])
               if e.get('kind') != 'behavior_callback']
    includes = [(name, path) for name in entries if name in own['trees'] for node, path in _walk(own['trees'][name]['root'])
                if node['op'] == 'IncludeTree' and _text(node, 'Name') == AUTOMATON]
    report = dict(module=module_name(model['quest']), dispatcher=None, aliases={}, requests=0, converted_requests=0,
                  not_owned={}, handed_to_playback=list(HANDED_TO_PLAYBACK), runtime_verified=False)
    found = {}
    for tree, path, node in requests(model):
        report['requests'] += 1
        parsed = fields(node['attributes'].get('values', '')) or {}
        alias = parsed.get('alias', '').strip("'")
        found.setdefault(alias, []).append((tree, path, node, parsed))
    served = {}
    for alias, sites in sorted(found.items()):
        if alias not in owned:
            report['not_owned'][alias or '(no alias)'] = len(sites)
            continue
        reason = None
        saves = {(p.get('saveGameQuest', "''").strip("'"), p.get('saveGameObjective', "''").strip("'")) for *_, p in sites}
        for tree, path, node, parsed in sites:
            extra = set(parsed) - CONTROLLER_FIELDS - PLAYBACK_FIELDS
            if not parsed or not re.fullmatch(r"'[A-Za-z_]\w*'", parsed.get('alias', '')):
                reason = 'request is not a literal field list'
            elif extra:
                reason = 'fields the controller cannot serve: ' + ', '.join(sorted(extra))
            elif parsed.get('state', '$enum:cutsceneState.doStart') != '$enum:cutsceneState.doStart':
                reason = 'request does not start a scene'
            elif node['op'] != 'InstantSendMessageToNPC' or _text(node, 'target') not in SELF:
                reason = 'request is not an instant send to the controller'
            elif (_text(node, 'target').lstrip('$') == 'this.id' and tree not in entries
                  and not tree.startswith('cutscene_')):
                # Elsewhere `this` may be an NPC running one of the controller's behaviours.
                reason = 'request to this.id from a tree the controller may not run itself'
        if reason is None and len(saves) != 1:
            reason = 'requests disagree on the save objective'
        if reason is None and 'cutscene_' + alias not in own['trees']:
            reason = 'no cutscene_' + alias + ' tree'
        if reason is None and len(includes) != 1:
            reason = 'the entry tree does not include the scene automaton exactly once'
        quest, objective = next(iter(saves))
        if reason is None and objective and not re.fullmatch(r'[A-Za-z_]\w*', objective):
            reason = 'save objective is not a literal name'
        report['aliases'][alias] = dict(requests=len(sites), converted=reason is None, reason=reason,
                                        save=dict(quest=quest or model['quest'], objective=objective) if objective else None,
                                        playback_fields=sorted({f for *_, p in sites for f in set(p) & PLAYBACK_FIELDS}))
        if reason is None:
            served[alias] = report['aliases'][alias]['save']
            report['converted_requests'] += len(sites)
    return served, report


def dispatcher(model, served):
    """The generated tree that stands where KCD1's scene automaton was."""
    module, file = module_name(model['quest']), '"quests/' + model['quest'].lower() + '.xml"'
    branches = []
    for alias, save in sorted(served.items()):
        steps = [_node('SuppressFailure', [_node('IncludeTree', File=file, Name='"cutscene_' + alias + '"')])]
        if save:
            target = dict(quest='"' + save['quest'] + '"', objective='"' + save['objective'] + '"')
            for state, action in (('IsObjectiveUnchanged', 'StartObjective'), ('IsObjectiveStarted', 'CompleteObjective')):
                steps.append(_node('QuestObjectiveCondition', [_node('Then', [_node(
                    'SetQuestObjective', function='"' + action + '"', **target)], canSkip='1')],
                    function='"' + state + '"', failSubtMissing='"false"', saveVersion='2', **target))
        steps += [_node('SceneSignal', module=module, port='done_' + alias),
                  _node('ScenePending', [_node('Success')], module=module, port='pending_' + alias,
                        Negation='"true"', RunLogic='"KeepRunning"')]
        branches.append(_node('Loop', [_node('ScenePending', [_node('Sequence', steps)], module=module,
                                             port='pending_' + alias, Negation='"false"', RunLogic='"KeepRunning"')],
                              count='"-1"'))
    body = _node('Parallel', branches, successMode='"Any"', failureMode='"Any"')
    root = _node('Root', [_node('Behavior', [body], canSkip='1')], OneTimeOnly='"false"', FailState='"Recoverable"',
                 saveVersion='2')
    return dict(variables=[], root=root, generated='scene dispatcher')


def apply(model, owned):
    """Rewrite the model in place for the owned aliases; return the seam report."""
    served, report = plan(model, owned)
    if not served:
        return report
    own = model['behavior_documents']['libs/ai/quests/' + model['quest'].lower() + '.xml']
    name, module = dispatcher_name(model['quest']), module_name(model['quest'])
    if name in own['trees']:
        raise ValueError('Scene dispatcher name is taken: ' + name)
    for tree, path, node in list(requests(model)):
        alias = (fields(node['attributes'].get('values', '')) or {}).get('alias', '').strip("'")
        if alias in served:
            node.update(op='SceneSignal', attributes=dict(module=module, port='play_' + alias), source_op='InstantSendMessageToNPC')
    for body in own['trees'].values():
        for node, _ in _walk(body['root']):
            if node['op'] == 'IncludeTree' and _text(node, 'Name') == AUTOMATON:
                node['attributes'] = dict(node['attributes'], File='"quests/' + model['quest'].lower() + '.xml"',
                                          Name='"' + name + '"')
                node['source_op'] = 'IncludeTree ' + AUTOMATON
    own['trees'][name] = dispatcher(model, served)
    report['dispatcher'] = name
    report['wiring'] = [w for alias in sorted(served) for w in (
        dict(alias=alias, bridge='signal', module_port='play_' + alias, direction='In', type='trigger', exists_in_c5=True),
        dict(alias=alias, bridge='context', module_port='pending_' + alias, direction='Out', type='bool', exists_in_c5=False),
        dict(alias=alias, bridge='signal', module_port='done_' + alias, direction='In', type='trigger', exists_in_c5=False))]
    return report


def _signal(compiler, source, owner):
    record = dict(kind='action', quest=source['attributes']['module'], port=source['attributes']['port'],
                  source_operation='SceneSignal')
    record['name'] = compiler.bridge._name('action', record['quest'], record['port'])
    compiler.bridge.actions[record['name']] = record
    return ET.Element('SendAIConceptSignal_' + record['name'])


def _pending(compiler, source, owner):
    record = dict(kind='condition', quest=source['attributes']['module'], port=source['attributes']['port'],
                  source_operation='ScenePending')
    record['name'] = compiler.bridge._name('condition', record['quest'], record['port'])
    compiler.bridge.conditions[record['name']] = record
    attributes = dict(context='"' + record['name'] + '"', Negation=source['attributes']['Negation'],
                      RunLogic=source['attributes']['RunLogic'])
    return dict(source, op='GameContextBarrier', attributes=attributes)


LOWERINGS = {'SceneSignal': _signal, 'ScenePending': _pending}
