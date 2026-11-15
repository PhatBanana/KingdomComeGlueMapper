"""Generic source-side preparation for quest-controller conversion (C2).

`prepare(models)` returns rewritten copies of quest IR models plus a report;
`register()` adds operation contracts to the behaviour compiler. Nothing here
names a quest, an actor or a site. Four rules:

1. Document scope. A KCD1 controller tree that is entered through IncludeTree
   or a callback runs in its caller's variable scope: retail callback trees use
   names such as `t_actors[x]` with an empty <Variables/> of their own. A bare
   index `name[key]` is therefore typed from the controller document when the
   tree does not declare `name`: every tree of that document that declares it
   must declare it associative, and `key` must not itself be a variable in
   either scope. The key is then quoted, exactly as
   campaign_behavior.associative_indexes does for a locally declared map. No
   declaration is added to the tree, so no variable is shadowed.

2. Rewritten operations. An operation whose KCD2 node has another name is
   rewritten on the source side, attribute by attribute: a plain rename
   (RENAMES) or a function (REWRITES) when the native shape differs. Each
   entry records its evidence; a field or shape outside the rule blocks the
   node, which then keeps its source name and its typed residue reason.

3. Same-name contracts. An operation that exists in KCD2 under the same name,
   whose source attributes all occur on native examples, gets a contract with
   the serialisation kinds read from those examples.

4. Dependency fields and typed residue. `register()` wraps the compiler's
   node lowering (no maintainer file is edited): POST resolves the fields a
   plain contract cannot (world profile, buff, link data symbol) through the
   dependency importer, and RESIDUE replaces the generic "needs an adapter"
   reason of an operation that has no native equivalent with what is missing.

Not runtime-verified.
"""
import copy
import re

SCRIPT_ATTRIBUTES = {'code', 'onEnter', 'onExit', 'onUpdate'}
INDEX = re.compile(r'(\$?)([A-Za-z_]\w*)\[([A-Za-z_]\w*)\]')
QUOTED = re.compile(r'''(&apos;.*?&apos;|'(?:\\.|[^'\\])*')''')

# source op -> (native op, {source attribute: native attribute}, evidence)
RENAMES = {
    'TurnBody': ('Turn', dict(destinationSpecification='target', alignWith='align', destinationType='destinationType',
                              stopWithinAngle='stopWithinAngle', randomMinAngle='randomMinAngle',
                              randomMaxAngle='randomMaxAngle', randomTurnRightChance='randomTurnRightChance',
                              stopRunninganimation='stopRunninganimation'),
                 'KCD2 Turn carries the six unrenamed TurnBody fields verbatim (AI/_lukas/test_lukas_helper.xml); '
                 'target/align hold a variable and a boolean as destinationSpecification/alignWith do. Inference.'),
    'JoinedAnimationSynchronize': ('Synchronize', {name: name for name in (
        'SemaphoreCount', 'InsideTimerValue', 'InvalidateOnExpire', 'atomic', 'OutsideQueuePosVariable',
        'InsidePosVariable', 'TimerType', 'OutsideTimerValue', 'LockManagerType', 'SemaphoreName', 'RunLogic')},
        'KCD2 has no JoinedAnimationSynchronize (no XML use, no string in WHGame.dll); its Synchronize has exactly '
        'these eleven fields (262 uses, AI/carts/carts.xml). The participant gate is kept. Inference: any '
        'animation phase alignment the KCD1 node added belongs to the animation adapter (native '
        'JoinedAnimationAction lockName/lockCount), not to this gate.'),
}
# A plain rename is childless unless listed here.
RENAMES_WITH_CHILDREN = {'JoinedAnimationSynchronize'}
# Kinds follow native serialisation: GameOver Reason="DiedInCombat" (bare),
# ExecuteSoundTrigger triggerName="'boar_hit'" entity="$this.id",
# HasActiveThreats SoulWUID="$__player", UnionOp booleans bare,
# ProfileLoadedGate LayerName="'zranenyLovci_horse'" NegateTo="false",
# AddPerceivableState PerceivableLabel="'crime_interrupt'" (labels are free
# strings: no table lists them and HasPerceivableState reads quest-private
# ones such as 'svatba_winePicked'), EvaLLyzer
# Expresion="$a = $__link_crime_reactor.information", Look
# destinationSpecification="$__player" destinationType="FromVariable",
# MoraleGate Target="" Low="$data:script_param[...].value" Negation="false",
# DecoratorBuff BuffId="'<guid>'" SoulWUID="$this.id", TeleportAction
# Position="$tagpoint", ActorStateBarrier Who="$this.id" ToState="land",
# AreaPresenceGate aiObjects="$__player" area="$area" amount="AtLeastOne"
# presence="Present", AreaPresenceListener trackIn="true",
# DetailBehaviorBarrier RunLogic="Halt".
CONTRACTS = {
    'Turn': dict(target='reference', align='value', destinationType='value', stopWithinAngle='value',
                 randomMinAngle='value', randomMaxAngle='value', randomTurnRightChance='value',
                 stopRunninganimation='value'),
    'GameOver': dict(Reason='value'),
    'ExecuteSoundTrigger': dict(entity='reference', triggerName='string_expression', stop='value'),
    'HasActiveThreats': dict(SoulWUID='reference', FailSubtMissing='value', saveVersion='value'),
    'UnionOp': dict(Results='value', Advance='value', EndOp='value', ShortCircuit='value', LocalNodalyzers='value'),
    'ProfileLoadedGate': dict(LayerName='string_expression', NegateTo='value', RunLogic='value'),
    'AddPerceivableState': dict(PerceivableLabel='string_expression'),
    'EvaLLyzer': dict(Expresion='expression', Quantifiers='value', saveVersion='value'),
    'Look': dict(destinationSpecification='reference', destinationType='value'),
    'MoraleGate': dict(Target='reference', Low='expression', High='expression', Negation='value', RunLogic='value'),
    'DecoratorBuff': dict(BuffId='string_expression', SoulWUID='reference'),
    'TeleportAction': dict(Position='reference', EndInterruptOnActionStart='value'),
    'ActorStateBarrier': dict(Who='reference', ToState='value', NegateTo='value', RunLogic='value'),
    'AreaPresenceGate': dict(aiObjects='reference', area='reference', amount='value', presence='value',
                             RunLogic='value'),
    'AreaPresenceListener': dict(aiObjects='reference', area='reference', trackIn='value', trackOut='value',
                                 reportInitialState='value'),
    'DetailBehaviorBarrier': dict(RunLogic='value'),
}
# ActorStateBarrier ToState / ActorStateCheck State values on native examples.
ACTOR_STATES = {'idle', 'minigame', 'jump', 'actorAnim', 'reading', 'readingFromInventory', 'carried', 'land',
                'carryItem', 'ragdoll', 'dead', 'crouch', 'sprinting', 'hit', 'combat', 'ladder', 'stoneThrowing',
                'battleArcheryNpc', 'skipTime', 'horse', 'fastTravel', 'carryCorpse', 'unconscious'}
# Operations with no native operation of the same meaning. The reason replaces
# "Behavior operation needs an adapter"; the evidence is in the blocker ledger.
RESIDUE = {
    'FinishPatch': 'Daycycle patch end needs the scheduled-activity lease: FinishPatch',
    'AddOpponent': 'Inexpressible as one native operation: AddOpponent (AddToSkirmish holds only while it runs)',
    'MakeMeIdle': 'Inexpressible as one native operation: MakeMeIdle (no idle-reset operation)',
    'LODCheck': 'Inexpressible as one native operation: LODCheck (no one-shot LOD test)',
    'LOD': 'Inexpressible as one native operation: LOD (branch of an unconverted LOD operation)',
    'Detail': 'Inexpressible as one native operation: Detail (branch of an unconverted LOD operation)',
    'LODGuardian': 'Inexpressible as one native operation: LODGuardian (shape outside the DetailBehaviorBarrier rule)',
    'LODLock': 'Inexpressible as one native operation: LODLock (outside a LODGuardian Detail branch)',
    'InstantDrawWeapon': 'Inexpressible as one native operation: InstantDrawWeapon (DrawAction always animates)',
    'DrawWeapon': 'Native operation lacks source fields: DrawWeapon (DrawAction has no ToCombatGuard, noAnimation, who)',
    'AnimationEventCatch': 'Native operation has no shipped example: AnimationEventCatch (name in WHGame.dll only)',
    'OnEvent': 'Native operation has no shipped example: OnEvent (branch of AnimationEventCatch)',
    'SetOwner': 'Native operation lives in the quest graph: SetOwner (Skald Effect What/Who; needs a signal bridge)',
}


class Blocked(ValueError):
    """A rewrite rule does not cover this node; it keeps its source operation."""


def _text(node, name, default=''):
    raw = node['attributes'].get(name, default)
    return raw[1:-1] if len(raw) >= 2 and raw[0] == raw[-1] == '"' else raw


def _node(op, children=(), **attributes):
    return dict(op=op, attributes={k: '"' + v + '"' for k, v in attributes.items()}, children=list(children), text='')


def _only(node, allowed, children=None):
    extra = sorted(set(node['attributes']) - set(allowed))
    if extra:
        raise Blocked('unmapped fields: ' + ', '.join(extra))
    if children is not None and len(node['children']) != children:
        raise Blocked('expected %d children, found %d' % (children, len(node['children'])))


def _teleport(node):
    """Teleport(Position, Target) -> TeleportAction(Position).

    Native TeleportAction (96 uses) moves the acting NPC and has no target
    field, so only a self-teleport converts. EndInterruptOnActionStart is
    optional natively (absent on 19 uses) and stays unset.
    """
    _only(node, ('Position', 'Target'), 0)
    if _text(node, 'Target') not in ('', 'this.id', '$this.id'):
        raise Blocked('teleport of another entity has no native action')
    return dict(node, op='TeleportAction', attributes=dict(Position=node['attributes'].get('Position', '""')))


def _state_gate(node):
    """StateMachineGate(Who, State, NegateTo, RunLogic) -> ActorStateBarrier(Who, ToState, NegateTo, RunLogic).

    Same four fields (56 native uses). Inference: the state names kept their
    meaning with a lower-case initial (Combat -> combat, CarryCorpse ->
    carryCorpse); a name not seen on a native example blocks the node.
    """
    _only(node, ('Who', 'State', 'NegateTo', 'RunLogic'), 1)
    state = _text(node, 'State')
    state = state[:1].lower() + state[1:]
    if state not in ACTOR_STATES:
        raise Blocked('actor state has no native example: ' + _text(node, 'State'))
    attributes = {k: v for k, v in node['attributes'].items() if k != 'State'}
    return dict(node, op='ActorStateBarrier', attributes=dict(attributes, ToState='"' + state + '"'))


def _install_gate(node):
    """StreamingInstallGate(Content, RunLogic) -> IfGate(condition true, RunLogic).

    KCD2 has no streaming-install node (no XML use, no string in WHGame.dll).
    Inference: on a PC installation the additional content is always present,
    so the gate is the always-open native gate with the same run logic.
    """
    _only(node, ('Content', 'RunLogic'), 1)
    if _text(node, 'Content') != 'AdditionalContent':
        raise Blocked('unknown install content: ' + _text(node, 'Content'))
    return dict(node, op='IfGate', attributes=dict(atomic='"false"', condition='"true"',
                                                   RunLogic=node['attributes'].get('RunLogic', '"KeepRunning"')))


def _area_presence(node):
    """AreaPresence -> AreaPresenceGate (Once) or AreaPresenceListener (repeating).

    KCD1 reports the state that already holds when the node starts: its
    ReportInitialState is an output flag (Libs/AI/final/npc_guarddog.xml undoes
    a count only when `$presenceState == false`). So a one-shot AreaPresence is
    the native level gate (117 uses; `presence` Present for TrackIn, NotThere
    for TrackOut), and a repeating one is the native listener with
    reportInitialState true. Inference: the native listener keeps listening
    after its child ends (drevorubecAVlci.xml keeps a membership array inside
    Parallel/Any), and `amount` AtLeastOne is right for one tracked object
    but unproven for an array. Atomic becomes an AtomicDecorator around the
    child. The
    output variables have no native field (the listener exposes $__presence
    and $__presenceObject instead), so a node that names one stays blocked.
    """
    _only(node, ('NPCs', 'Area', 'TrackIn', 'TrackOut', 'Once', 'Atomic', 'OutNPC', 'OutEvent',
                 'ReportInitialState'), 1)
    for name in ('OutNPC', 'OutEvent', 'ReportInitialState'):
        if _text(node, name):
            raise Blocked('output variable has no native field: ' + name)
    flags = {name: _text(node, name, 'missing') for name in ('TrackIn', 'TrackOut', 'Once')}
    atomic = _text(node, 'Atomic', 'false')
    if any(value not in ('true', 'false') for value in (*flags.values(), atomic)):
        raise Blocked('flag is not a literal boolean')
    if 'NPCs' not in node['attributes'] or 'Area' not in node['attributes']:
        raise Blocked('missing NPCs or Area')
    common = dict(aiObjects=node['attributes']['NPCs'], area=node['attributes']['Area'])
    if flags['Once'] == 'true':
        if flags['TrackIn'] == flags['TrackOut']:
            raise Blocked('a one-shot gate needs exactly one of TrackIn and TrackOut')
        attributes = dict(common, amount='"AtLeastOne"', RunLogic='"KeepRunning"',
                          presence='"Present"' if flags['TrackIn'] == 'true' else '"NotThere"')
        op = 'AreaPresenceGate'
    else:
        if flags['TrackIn'] == flags['TrackOut'] == 'false':
            raise Blocked('nothing is tracked')
        attributes = dict(common, trackIn='"%s"' % flags['TrackIn'], trackOut='"%s"' % flags['TrackOut'],
                          reportInitialState='"true"')
        op = 'AreaPresenceListener'
    children = node['children'] if atomic == 'false' else [_node('AtomicDecorator', node['children'])]
    return dict(node, op=op, attributes=attributes, children=children)


def _lod_guardian(node):
    """LODGuardian{LOD{Wait -1}, Detail{X}} -> DetailBehaviorBarrier{X}.

    KCD2 has no LODGuardian, LODCheck or LODLock (no XML use, no string in
    WHGame.dll); its one detail-scoped decorator is DetailBehaviorBarrier
    (RunLogic only, 5 uses). Inference from KCD1's own comments ("To allow
    instant switch to LOD, guardian must be used"; LODLock: "atomic with
    regards to LODGuardian"): a guardian that only waits in LOD and ends its
    Detail branch on a switch is the barrier with RunLogic Halt, and a Detail
    branch wholly inside LODLock is the barrier with KeepRunning. StatProp
    FailAlways is the barrier followed by Fail in a Sequence. Any other shape
    stays blocked.
    """
    _only(node, ('LODTerm', 'StatProp', 'saveVersion', 'nodeLabel'), 2)
    lod, detail = node['children']
    if (lod['op'], detail['op']) != ('LOD', 'Detail') or len(lod['children']) != 1 or len(detail['children']) != 1:
        raise Blocked('expected one LOD and one Detail branch with one child each')
    wait = lod['children'][0]
    if wait['op'] != 'Wait' or _text(wait, 'duration') != '-1' or wait['children']:
        raise Blocked('the LOD branch does more than wait')
    if _text(node, 'LODTerm') != 'OnBoth' or _text(node, 'StatProp') not in ('PropagateChild', 'FailAlways'):
        raise Blocked('unknown LODTerm or StatProp')
    body, logic = detail['children'][0], 'Halt'
    if body['op'] == 'LODLock':
        _only(body, (), 1)
        body, logic = body['children'][0], 'KeepRunning'
    barrier = _node('DetailBehaviorBarrier', [body], RunLogic=logic)
    if _text(node, 'StatProp') == 'FailAlways':
        return _node('Sequence', [barrier, _node('Fail')])
    return barrier


# source op -> (native shape, rule). The rule's docstring is its evidence.
REWRITES = {'Teleport': ('TeleportAction', _teleport), 'StateMachineGate': ('ActorStateBarrier', _state_gate),
            'StreamingInstallGate': ('IfGate', _install_gate),
            'AreaPresence': ('AreaPresenceGate or AreaPresenceListener', _area_presence),
            'LODGuardian': ('DetailBehaviorBarrier', _lod_guardian)}


def _rename(source):
    target, mapping, _ = RENAMES[source]

    def rewrite(node):
        _only(node, mapping, None if source in RENAMES_WITH_CHILDREN else 0)
        return dict(node, op=target, attributes={mapping[k]: v for k, v in node['attributes'].items()})
    return rewrite


def _profile(compiler, node, source, site, record):
    """LayerName is a world profile: the gate must name the converted one."""
    from campaign_behavior import quote, UnsupportedOperation
    name = _text(source, 'LayerName')
    if not re.fullmatch(r'[A-Za-z_]\w*', name):
        raise UnsupportedOperation('Dynamic profile identity requires runtime mapping: ' + name)
    target = compiler.importer.ensure('world_profiles', name, site) if compiler.importer else None
    if target is None:
        raise UnsupportedOperation('Referenced world profile conversion did not complete: ' + name)
    node.set('LayerName', quote(target))


def _buff(compiler, node, source, site, record):
    """BuffId is a buff definition, converted as AddBuff's BuffGUID is."""
    from campaign_behavior import quote, UnsupportedOperation
    buff = _text(source, 'BuffId')
    record['buff_dependencies'].append(dict(buff=buff, site=site))
    if not buff or buff.startswith('$'):
        raise UnsupportedOperation('Dynamic, empty or tag-selected buffs require a runtime buff map')
    target = compiler.importer.ensure('buffs', buff, site) if compiler.importer else None
    if target is None:
        raise UnsupportedOperation('Referenced buff conversion did not complete: ' + buff)
    node.set('BuffId', quote(target))


def _link_expression(compiler, node, source, site, record):
    """A `$name` that is no tree variable is the link data of the edge under test.

    KCD1 `$questName = $QuestActor`; native `$a = $__link_<type>`.
    """
    from campaign_behavior import UnsupportedOperation
    from campaign_link_types import data_expression
    value = node.get('Expresion', '')
    code = ''.join(part for i, part in enumerate(QUOTED.split(value)) if not i % 2)
    names = {m for m in re.findall(r'\$([A-Za-z_]\w*)', code) if not m.startswith('__') and m not in compiler.variables}
    adapter = compiler.importer.adapters.get('link_types') if compiler.importer else None
    for name in sorted(names):
        rows = [row for row in adapter.source.values()
                if (row.get('variableName') or row['name']) == name] if adapter else []
        if len(rows) != 1:
            raise UnsupportedOperation('Missing or ambiguous link-data symbol: ' + name)
        target = compiler.importer.ensure('link_types', rows[0]['name'], site)
        if target is None:
            raise UnsupportedOperation('Referenced AI link type conversion did not complete: ' + rows[0]['name'])
        value = data_expression(value, name, target)
    node.set('Expresion', value)


# native op -> hook(compiler, emitted node, source node, site, record)
POST = {'ProfileLoadedGate': _profile, 'DecoratorBuff': _buff, 'EvaLLyzer': _link_expression}
GENERIC = 'Behavior operation needs an adapter: '


def register():
    """Add the contracts above to the behaviour compiler. Existing entries win.

    Also wraps BehaviorCompiler.lower_node once, for POST and RESIDUE. A hook
    runs only for an operation whose contract is ours.
    """
    import campaign_behavior
    added = [op for op in CONTRACTS if op not in campaign_behavior.CONTRACTS]
    for op in added:
        campaign_behavior.CONTRACTS[op] = dict(CONTRACTS[op])
    original = campaign_behavior.BehaviorCompiler.lower_node
    if not hasattr(original, 'controller_contracts'):
        def lower_node(self, source, owner, document, tree, path, record, animation_controllers=None):
            before = len(record['unresolved'])
            node = original(self, source, owner, document, tree, path, record, animation_controllers)
            for entry in record['unresolved'][before:]:
                reason = entry.get('reason', '')
                if reason.startswith(GENERIC) and reason[len(GENERIC):] in RESIDUE:
                    entry['reason'] = RESIDUE[reason[len(GENERIC):]]
            op = source['op']
            if node is not None and op in POST and op in lower_node.controller_contracts:
                site = dict(owner=owner, document=document, tree=tree, path=path, operation=op,
                            arguments=source['attributes'])
                try:
                    POST[op](self, node, source, site, record)
                except campaign_behavior.UnsupportedOperation as error:
                    record['unresolved'].append(dict(site=site, reason=str(error)))
                    self.converted[op] -= 1
                    return None
            return node
        lower_node.controller_contracts = set()
        campaign_behavior.BehaviorCompiler.lower_node = lower_node
    campaign_behavior.BehaviorCompiler.lower_node.controller_contracts.update(added)
    return added


def document_scope(payload):
    """{name: declaration} for names every declaring tree of a document agrees on."""
    seen, conflict = {}, set()
    for tree in payload['trees'].values():
        for variable in tree['variables']:
            name, shape = variable.get('name'), (variable.get('form'), variable.get('type'))
            if name in seen and (seen[name].get('form'), seen[name].get('type')) != shape:
                conflict.add(name)
            seen.setdefault(name, variable)
    return {name: v for name, v in seen.items() if name not in conflict}


def _walk(node, path='Root'):
    yield node, path
    for index, child in enumerate(node['children']):
        yield from _walk(child, path + '/' + str(index))


def prepare(models):
    """Return (models, report). Inputs are not modified."""
    models = copy.deepcopy(models)
    report = dict(scope_resolutions=[], renamed=[], rename_blocked=[], runtime_verified=False)
    for model in models:
        for document, payload in model['behavior_documents'].items():
            scope = document_scope(payload)
            for name, tree in payload['trees'].items():
                local = {v.get('name') for v in tree['variables']}
                site = dict(quest=model['quest'], document=document, tree=name)

                def typed(match, attribute, path):
                    base, key = match[2], match[3]
                    if base in local or key in local or key in scope:
                        return match[0]
                    if scope.get(base, {}).get('form') != 'associative':
                        return match[0]
                    report['scope_resolutions'].append(dict(site, path=path, attribute=attribute, source=match[0]))
                    return match[1] + base + "['" + key + "']"

                # Preorder: a rewritten node's new children are walked after it.
                # `path` is the node's position in the tree as rewritten so far.
                for node, path in _walk(tree['root']):
                    for attribute, raw in list(node['attributes'].items()):
                        if attribute in SCRIPT_ATTRIBUTES or '[' not in raw:
                            continue
                        parts = QUOTED.split(raw)
                        node['attributes'][attribute] = ''.join(
                            part if i % 2 else INDEX.sub(lambda m: typed(m, attribute, path), part)
                            for i, part in enumerate(parts))
                    source_op = node['op']
                    rule = REWRITES[source_op][1] if source_op in REWRITES else (
                        _rename(source_op) if source_op in RENAMES else None)
                    if rule is None:
                        continue
                    try:
                        rewritten = rule(node)
                    except Blocked as error:
                        unmapped = sorted(set(node['attributes']) - set(RENAMES[source_op][1])) \
                            if source_op in RENAMES else []
                        report['rename_blocked'].append(dict(site, path=path, operation=source_op, unmapped=unmapped,
                                                             reason=str(error)))
                        continue
                    report['renamed'].append(dict(site, path=path, source=source_op, target=rewritten['op']))
                    node.clear()
                    node.update(rewritten, source_op=source_op)
    report['rename_evidence'] = dict({source: entry[2] for source, entry in RENAMES.items()},
                                     **{source: ' '.join(entry[1].__doc__.split()) for source, entry in REWRITES.items()})
    return models, report
