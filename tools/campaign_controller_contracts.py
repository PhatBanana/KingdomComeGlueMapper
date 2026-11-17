"""Generic source-side preparation for quest-controller conversion (C2).

`prepare(models)` returns rewritten copies of quest IR models plus a report;
`register()` adds operation contracts to the behaviour compiler. Nothing here
names a quest, an actor or a site. Four rules:

1. Document scope. A KCD1 controller tree that is entered through IncludeTree
   or a callback runs in its caller's variable scope: retail callback trees use
   names such as `t_actors[x]` with an empty <Variables/> of their own. A bare
   index `name[key]` is therefore typed from the controller document when the
   tree does not declare `name`: every tree of that document that declares it
   must declare it associative. The key is then quoted, as
   campaign_behavior.associative_indexes does for a locally declared map. No
   declaration is added to the tree, so no variable is shadowed. A bare key
   is a literal even when a variable has the same name: KCD1 writes a
   variable index with `$` (`kunesThings[$kunesThings_iterator]`), the same
   document spells one place `t_places['henrysHome']` and
   `t_places[henrysHome]`, and the namesakes (`kunes`, `tereza`) are WUIDs,
   which cannot key a string map. Only a string variable of that name in the
   document leaves the index untouched (and blocked).

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
                              stopRunninganimation='stopRunninganimation', allowInstantSuccess='allowInstantSuccess'),
                 'KCD2 Turn carries the seven unrenamed TurnBody fields verbatim on six retail nodes '
                 '(AI/quests/questUtils.xml, zranenylovci, lecenipecky, mlynarskyucen, pytlakptacek), each with one '
                 'value (TURN_VALUES). target/align hold a variable and a boolean as destinationSpecification/alignWith '
                 'do. Inference. WHGame.dll names destinationType and none of the other six, so KCD2 most likely '
                 'does not read them: a value other than the one retail writes would be lost and blocks the node.'),
    'JoinedAnimationSynchronize': ('Synchronize', {name: name for name in (
        'SemaphoreCount', 'InsideTimerValue', 'InvalidateOnExpire', 'atomic', 'OutsideQueuePosVariable',
        'InsidePosVariable', 'TimerType', 'OutsideTimerValue', 'LockManagerType', 'SemaphoreName', 'RunLogic')},
        'KCD2 has no JoinedAnimationSynchronize (no XML use, no string in WHGame.dll); its Synchronize has exactly '
        'these eleven fields (262 uses, AI/carts/carts.xml). The participant gate is kept. Inference: any '
        'animation phase alignment the KCD1 node added belongs to the animation adapter (native '
        'JoinedAnimationAction lockName/lockCount), not to this gate.'),
}
# The one value each legacy Turn field has on retail KCD2 nodes. KCD1 also writes stopWithinAngle 5 to 30,
# random angles and stopRunninganimation true; those have no native example.
TURN_VALUES = dict(stopWithinAngle='0.000000', randomMinAngle='0.000000', randomMaxAngle='0.000000',
                   randomTurnRightChance='0.000000', stopRunninganimation='false', allowInstantSuccess='true')
# source op -> {source attribute: the only value that converts}
RENAME_VALUES = {'TurnBody': TURN_VALUES}
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
                 stopRunninganimation='value', allowInstantSuccess='value'),
    # HasActiveThreatsGate Who="$__player" Negation="true" RunLogic="KeepRunning": the three KCD1 fields (8 uses).
    'HasActiveThreatsGate': dict(Who='reference', Negation='value', RunLogic='value'),
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
    # Targets of the approved stand-ins: StopMovement waitUntilStopped="false",
    # DrawAction WeaponSet="Primary" fullBody="false" tags="" useSelectedWeaponSet="false".
    'StopMovement': dict(waitUntilStopped='value'),
    'DrawAction': dict(WeaponSet='value', fullBody='value', tags='string_expression', useSelectedWeaponSet='value'),
    # The barrier the quest bridge emits for objective gates; the scene
    # dispatcher uses it with a context of its own (campaign_controller_scenes).
    'GameContextBarrier': dict(context='value', Negation='value', RunLogic='value'),
}
# Engine-owned records: absent from KCD1 TypeDefinitions, declared as variable
# types in retail KCD2 trees (the compiler still requires the type in the
# native catalog). Every field q_skalitz reads occurs on native uses:
# additionalMoveParams.destChangedThreshold, followFormationParams.formation
# and .leaderCallback, hearingInfo.soundId, perceptionInfo.perceptible and
# .threshold; transform is passed whole to Get/SetSpatialInfo.
ENGINE_TYPES = {'additionalMoveParams': 'additionalMoveParams', 'followFormationParams': 'followFormationParams',
                'common:transform': 'transform', 'hearingInfo': 'hearingInfo', 'perceptionInfo': 'perceptionInfo'}
# Native initialisers quote the time: destChangedThreshold('250ms') (50+ uses).
# KCD1 writes it quoted and bare; the bare form is quoted. Inference: equal.
TIME_INITIALISER = re.compile(r"(destChangedThreshold)\(([0-9]+(?:ms|s|m|h)?)\)")
# (op, attribute) -> {source value: value the compiler already lowers}.
# KCD1's gate states are Started, Completed, Canceled, AfterReset and
# StartedTrackingDone (WHGame.dll, 1,506 retail uses); its conditions are
# IsObjectiveStarted/Completed/Canceled/Unchanged and TrackedCompleted.
# Inference: AfterReset, the one gate state left for the fourth condition, is
# the untouched state the quest graph exposes as `<objective>_Unchanged`.
VALUE_RENAMES = {('QuestObjectiveGate', 'objectiveState'): {'AfterReset': 'Unchanged'}}
# With failSubtMissing a quest condition fails when the selected branch is not
# authored. The native check has no such field (context, saveVersion), so the
# absent branch is written out as a branch holding Fail: the same result.
BRANCHED = {'QuestCondition', 'QuestObjectiveCondition'}
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
    'TurnBody': 'Native operation lacks source fields: TurnBody (Turn reads target, align and destinationType)',
    'SetOwner': 'Native operation lives in the quest graph: SetOwner (Skald Effect What/Who take level assets; this object is found at run time)',
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


class NotApplicable(ValueError):
    """The node is not what the rule is about; it is left alone, unreported."""


SELF = ('', 'this.id', '$this.id')


def _stop_movement(node):
    """MakeMeIdle -> StopMovement(waitUntilStopped = WaitForFinish), for the acting NPC.

    KCD2 has no idle-reset operation; its animations and stances end with
    their node. StopMovement (30 uses) keeps a node at the site and covers
    the visible half. KeepStance, KeepAnimContext and AbortAnimation have no
    counterpart and are dropped.
    """
    _only(node, ('WaitForFinish', 'KeepStance', 'KeepAnimContext', 'AbortAnimation', 'Target'), 0)
    if _text(node, 'Target') not in SELF:
        raise Blocked('idle reset of another entity has no native action')
    if _text(node, 'WaitForFinish', 'false') not in ('true', 'false'):
        raise Blocked('WaitForFinish is not a literal boolean')
    return _node('StopMovement', waitUntilStopped=_text(node, 'WaitForFinish', 'false'))


def _draw_action(node):
    """DrawWeapon / InstantDrawWeapon -> DrawAction(WeaponSet), for the acting NPC.

    DrawAction (136 uses) is the only native draw: animated, generic, without
    a guard flag. The KCD1 animation tag, ToCombatGuard and noAnimation are
    dropped; an instant draw becomes an animated one.
    """
    _only(node, ('ToCombatGuard', 'tags', 'who', 'WeaponSet', 'noAnimation'), 0)
    if _text(node, 'who') not in SELF:
        raise Blocked('draw by another entity has no native action')
    if _text(node, 'WeaponSet') not in ('Primary', 'Secondary', 'Oversized'):
        raise Blocked('weapon set has no native example: ' + _text(node, 'WeaponSet'))
    return _node('DrawAction', WeaponSet=_text(node, 'WeaponSet'), fullBody='false', tags='',
                 useSelectedWeaponSet='false')


def _detail_branch(node):
    """LODCheck{LOD{..}, Detail{X}} -> X: the NPC is treated as simulated in detail.

    KCD2 has no one-shot LOD test. Near the player the result is the same;
    far away the detailed branch runs off-screen.
    """
    _only(node, ('saveVersion', 'nodeLabel'))
    detail = [child for child in node['children'] if child['op'] == 'Detail']
    if len(detail) != 1 or len(detail[0]['children']) != 1 or any(c['op'] not in ('LOD', 'Detail') for c in node['children']):
        raise Blocked('expected one Detail branch with one child')
    return dict(detail[0]['children'][0])


def _after_animation(node):
    """PlayAnimation{AnimationEventCatch End{OnEvent{Y}}} -> Sequence{PlayAnimation, Y}.

    For the End event, "when the animation ends" and "after the animation" are
    the same moment. Native AnimationEventCatch has no shipped example. Any
    other event name, or captured variables, stays blocked.
    """
    catches = [child for child in node['children'] if child['op'] == 'AnimationEventCatch']
    if not catches:
        raise NotApplicable()
    catch = catches[0]
    _only(catch, ('EventName', 'InterruptSafe', 'CapturedVariablesByValue', 'saveVersion'), 1)
    if len(node['children']) != 1 or _text(catch, 'EventName') != 'End' or _text(catch, 'CapturedVariablesByValue'):
        raise Blocked('only a single End event without captured variables continues after the animation')
    event = catch['children'][0]
    if event['op'] != 'OnEvent' or not event['children']:
        raise Blocked('expected one OnEvent branch with content')
    return _node('Sequence', [dict(node, children=[])] + event['children'])


SAVE_VERSION = re.compile(r'\$__version\.loaded\s*<\s*\$enum:gameVersion\.[A-Za-z_]\w*')


def _no_old_save(node):
    """IfCondition `$__version.loaded < $enum:gameVersion.<KCD1 patch>` -> condition false.

    A KCD1 save-migration check: it runs a fix-up when a save made before a
    KCD1 patch is loaded. No KCD1 save can be loaded into the port, so no save
    predates those patches. The branch is kept under a false condition.
    KCD2's own `$__version.loaded` counts KCD2 versions, so converting the
    enum would compare unrelated numbers. Remove this entry to reverse it.
    """
    if not SAVE_VERSION.fullmatch(_text(node, 'condition').strip()):
        raise NotApplicable()
    return dict(node, attributes=dict(node['attributes'], condition='"false"'))


# Stand-ins: KCD1 operations with no faithful KCD2 form, replaced by the
# closest native one by decision. Each use is reported as `stand_in`, never as
# a faithful conversion. source op -> (native shape, rule, approval).
# A stand-in that needs more than its own node is a pass of its own and adds
# its entries to the report's `stand_in_rules`: the library trees a controller
# includes (campaign_controller_library.rules, decisions 14 to 16).
APPROVED = 'Sean, 2026-11-14 (relayed by the coordinator)'
STAND_INS = {'MakeMeIdle': ('StopMovement', _stop_movement, APPROVED),
             'InstantDrawWeapon': ('DrawAction', _draw_action, APPROVED),
             'DrawWeapon': ('DrawAction', _draw_action, APPROVED),
             'LODCheck': ('the Detail branch', _detail_branch, APPROVED),
             'PlayAnimation': ('Sequence after the animation', _after_animation, APPROVED),
             'IfCondition': ('IfCondition false', _no_old_save,
                             'Sean, 2026-11-16 (relayed by Build): told of the stand-in, did not object')}


# source op -> (native shape, rule). The rule's docstring is its evidence.
REWRITES = {'Teleport': ('TeleportAction', _teleport), 'StateMachineGate': ('ActorStateBarrier', _state_gate),
            'StreamingInstallGate': ('IfGate', _install_gate),
            'AreaPresence': ('AreaPresenceGate or AreaPresenceListener', _area_presence),
            'LODGuardian': ('DetailBehaviorBarrier', _lod_guardian)}


def _rename(source):
    target, mapping, _ = RENAMES[source]

    def rewrite(node):
        _only(node, mapping, None if source in RENAMES_WITH_CHILDREN else 0)
        for name, native in RENAME_VALUES.get(source, {}).items():
            if name in node['attributes'] and _text(node, name) != native:
                raise Blocked('value has no native example: %s %s' % (name, _text(node, name)))
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


# Lua that runs unchanged. A script passes only when every call it makes is
# listed here and every string literal is an index key or listed below; the
# compiler then emits it verbatim, as it does a script identical to a native
# one. Evidence, retail KCD2: GetEntityByWUID in 168 tree scripts; `:Unlock()`
# on a door entity in 5; `player.player:SetPlayerHorse(<entity>.id)` in 1;
# System.GetCVar in 1 tree script and 8 Lua files, the cvar named in
# player.lua; DialogModule.SetAIInteractionState in DialogUtils.lua;
# inventory:GetMoney in 1 tree script; SocialClass.GetEntitySocialClassData
# and its diceMinimumBet field in SocialClass.lua; `data.x = ...`,
# `data.x['key']` and `__null` in tree scripts. Inference: a call that kept
# its name kept its meaning.
# `entity.actor:SetDialogAnimationState(true)` is a retail tree script
# (AI/player/scheduler/playeraction_setdialoganimationstate.xml; the name is
# in WHGame.dll); `tostring` is the Lua built-in (5 retail tree scripts).
VERBATIM_CALLS = {'XGenAIModule.GetEntityByWUID', '<entity>:Unlock', '<call>:Unlock', 'player.player:SetPlayerHorse',
                  'System.GetCVar', 'data=', 'DialogModule.SetAIInteractionState', 'entity.inventory:GetMoney',
                  'SocialClass.GetEntitySocialClassData', 'entity.actor:SetDialogAnimationState', 'tostring'}
VERBATIM_LITERALS = {'wh_sys_specVersion', 'expo'}
# A script may only start a name path at a local, at one of these, or at the
# root of a listed call. Anything else is a global KCD2 may not define, such
# as the enum tables KCD1 generates (`enum_animationOverride.userControlled`).
# `RPG.<parameter>` is read by 9 retail tree scripts (RPG.LowHealthThreshold).
VERBATIM_ROOTS = {'data', 'entity', 'player', '__null', 'RPG'} | {
    re.split(r'[.:]', call)[0] for call in VERBATIM_CALLS if call[0] != '<' and call != 'data='}
LUA_FIELDS = {'ExecuteLua': ('code',), 'LuaGate': ('code',), 'LuaWrapper': ('onEnter', 'onExit')}
# Numerical operations native trees use with the source's own operand form
# (`In1VariableName="this.id" In2VariableName="t_horse"`), beyond the three
# the compiler lists. The compiler still requires the name in the catalog.
# normalize: `In1VariableName="vecTargetToMe" OutVariableName="$vecTargetToMe"`
# (5 retail uses), one input and one output as round has.
NUMERIC_OPERATIONS = {'distance2dSq_wuid': 'distance2dSq', 'normalize': 'round'}


def verbatim_lua(script):
    from campaign_lua_contracts import tokens
    program = tokens(script)
    if not program or not set(lua_shape(script)) <= VERBATIM_CALLS:
        return False
    name = re.compile(r'[A-Za-z_]\w*')
    local = {program[i + 1] for i in range(len(program) - 1) if program[i] == 'local'}
    for index, token in enumerate(program):
        if token[:1] in ('"', "'", '[') and len(token) > 1 and token[1:-1] not in VERBATIM_LITERALS \
                and not (index and program[index - 1] == '['):
            return False
        if name.fullmatch(token) and token not in LUA_KEYWORDS and not (index and program[index - 1] in ('.', ':')) \
                and token not in local and token not in VERBATIM_ROOTS:
            return False
    return True


def _before(compiler, source, record):
    """Return (source to lower, finish(node)) for the two cases the generic path needs help with."""
    from campaign_lua_contracts import tokens
    op = source['op']
    for field in LUA_FIELDS.get(op, ()):
        script = _text(source, field)
        if script.strip() and verbatim_lua(script):
            compiler.lua_contracts.by_site.setdefault((op, field), set()).add(tokens(script))
            record.setdefault('verbatim_lua', []).append(dict(operation=op, field=field))
    operation = _text(source, 'Operation')
    if (op == 'NumericalOperation' and operation in NUMERIC_OPERATIONS
            and operation in compiler.catalog.get('numerical_operations', ())):
        stand_by = dict(source, attributes=dict(source['attributes'], Operation='"%s"' % NUMERIC_OPERATIONS[operation]))
        return stand_by, lambda node: node.set('Operation', operation)
    return source, None


# generated op -> handler(compiler, source node, owner): an emitted element for
# a leaf, or the source node to lower in its place. Filled by register().
LOWERINGS = {}
# native op -> hook(compiler, emitted node, source node, site, record)
POST = {'ProfileLoadedGate': _profile, 'DecoratorBuff': _buff, 'EvaLLyzer': _link_expression}
GENERIC = 'Behavior operation needs an adapter: '


def register():
    """Add the contracts above to the behaviour compiler. Existing entries win.

    Also wraps BehaviorCompiler.lower_node once, for POST and RESIDUE. A hook
    runs only for an operation whose contract is ours.
    """
    import campaign_ai_types
    import campaign_behavior
    import campaign_controller_scenes
    LOWERINGS.update(campaign_controller_scenes.LOWERINGS)
    import campaign_controller_ownership
    LOWERINGS.update(campaign_controller_ownership.LOWERINGS)
    import campaign_controller_combat
    for op, fields in campaign_controller_combat.CONTRACTS.items():
        CONTRACTS.setdefault(op, fields)
    import campaign_controller_library
    for op, fields in campaign_controller_library.CONTRACTS.items():
        CONTRACTS.setdefault(op, fields)
    for source, target in {**ENGINE_TYPES, **campaign_controller_library.ENGINE_TYPES}.items():
        campaign_ai_types.ENGINE_TYPE_ADAPTERS.setdefault(source, target)
    added = [op for op in CONTRACTS if op not in campaign_behavior.CONTRACTS]
    for op in added:
        campaign_behavior.CONTRACTS[op] = dict(CONTRACTS[op])
    original = campaign_behavior.BehaviorCompiler.lower_node
    if not hasattr(original, 'controller_contracts'):
        def lower_node(self, source, owner, document, tree, path, record, animation_controllers=None):
            # A rewritten node may name trees it needs emitted (`requires`) and
            # reasons it cannot be published yet (`blocked`).
            record['includes'].extend((owner, *needed) for needed in source.get('requires', ()))
            record['unresolved'].extend(
                dict(site=dict(owner=owner, document=document, tree=tree, path=path, operation=source['op'],
                               arguments=source['attributes']), reason=reason) for reason in source.get('blocked', ()))
            before = len(record['unresolved'])
            handler = LOWERINGS.get(source['op'])
            if handler is not None:
                result = handler(self, source, owner)
                if not isinstance(result, dict):
                    self.converted[source['op']] += 1
                    return result
                source = result
            lowered, finish = _before(self, source, record)
            node = original(self, lowered, owner, document, tree, path, record, animation_controllers)
            if node is not None and finish is not None:
                finish(node)
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


LUA_KEYWORDS = {'if', 'then', 'else', 'elseif', 'end', 'and', 'or', 'not', 'local', 'return', 'function', 'for',
                'while', 'do', 'in', 'repeat', 'until', 'nil', 'true', 'false'}


def lua_shape(script):
    """The sorted set of calls a script makes, for clustering Lua sites.

    Deterministic and lexical: literals are dropped, a local bound to
    XGenAIModule.GetEntityByWUID(...) is written `<entity>`, a method called
    on a call result `<call>`, and a write to a tree variable `data=`. Two
    sites with one shape need the same lowering apart from their constants.
    """
    from campaign_lua_contracts import tokens
    program = tokens(script)
    if program is None:
        return ('<unparsed>',)
    name = re.compile(r'[A-Za-z_]\w*')
    entities = {program[i - 1] for i in range(1, len(program) - 3)
                if program[i:i + 4] == ('=', 'XGenAIModule', '.', 'GetEntityByWUID')}
    calls = set()
    for index, token in enumerate(program):
        if token == '=' and index >= 3 and program[index - 3:index - 1] == ('data', '.'):
            calls.add('data=')
        if token != '(' or index == 0 or not name.fullmatch(program[index - 1]) or program[index - 1] in LUA_KEYWORDS:
            continue
        start = index - 1
        while start >= 2 and program[start - 1] in ('.', ':') and name.fullmatch(program[start - 2]):
            start -= 2
        chain = list(program[start:index])
        if start >= 2 and program[start - 1] in ('.', ':') and program[start - 2] == ')':
            chain = ['<call>', program[start - 1]] + chain
        elif chain[0] in entities:
            chain[0] = '<entity>'
        calls.add(''.join(chain))
    return tuple(sorted(calls))


def implicit_link_types(models):
    """{identity: row} for link tags that trees write but no definition declares.

    Both engines accept a tag absent from LinkTagDefinitions.xml (retail KCD2
    trees use `crime_reactor`, with data, undeclared). Such a tag converts only
    when a converted tree adds the link itself, so a writer of the converted
    tag exists; its data type is the type of the variable every writer passes.
    A tag that only level data or the engine writes is not listed and stays
    blocked. The caller adds these rows to the link-type adapter's source
    without replacing a declared one. Inference: declaring the converted tag
    with its name and type alone leaves the engine defaults an undeclared tag
    has.
    """
    rows, types = {}, {}
    for model in models:
        for payload in model['behavior_documents'].values():
            for tree in payload['trees'].values():
                declared = {v.get('name'): v.get('type') for v in tree['variables']}
                for node, _ in _walk(tree['root']):
                    tag = _text(node, 'Tag')
                    if node['op'] != 'AddLink' or not re.fullmatch(r'[A-Za-z_]\w*', tag):
                        continue
                    data = _text(node, 'Data').lstrip('$')
                    rows.setdefault(tag.lower(), dict(name=tag))
                    types.setdefault(tag.lower(), set()).add(declared.get(data) if data else None)
    for identity, row in rows.items():
        found = types[identity] - {None}
        if len(found) == 1:
            row['type'] = found.pop()
    return rows


def _walk(node, path='Root'):
    yield node, path
    for index, child in enumerate(node['children']):
        yield from _walk(child, path + '/' + str(index))


def controller_run_trees(model):
    """{name: tree} for the scene trees the controller's own brain runs.

    KCD1's scene handler is library code inside the controller: the entry tree
    includes `cutsceneAutomaton` (final/questUtils.xml), whose
    `cutsceneProgress` includes `cutscene_<alias>` from the quest's own file
    (`$cutsceneOnEndTree = 'cutscene_' + $t_cutscene.alias`). In those trees
    `this` is the controller object, although each is also registered as a
    behaviour of that object. So a daycycle request there that names
    `$this.id` as its source names the controller, which the lease adapter
    accepts only when written `$__object.id`.
    """
    own = model['behavior_documents'].get('libs/ai/quests/' + model['quest'].lower() + '.xml')
    entries = [e['tree'] for e in (model.get('controller_registration') or {}).get('entry_points', [])
               if e.get('kind') != 'behavior_callback']
    if not own or not any(node['op'] == 'IncludeTree' and _text(node, 'Name') == 'cutsceneAutomaton'
                          for name in entries if name in own['trees'] for node, _ in _walk(own['trees'][name]['root'])):
        return {}
    return {name: tree for name, tree in own['trees'].items() if name.startswith('cutscene_')}


def prepare(models):
    """Return (models, report). Inputs are not modified."""
    models = copy.deepcopy(models)
    report = dict(scope_resolutions=[], renamed=[], stand_ins=[], rename_blocked=[], initialisers=[], value_renames=[],
                  completed_branches=[], controller_scope=[],
                  implicit_links=implicit_link_types(models), runtime_verified=False)
    for model in models:
        for tree, body in controller_run_trees(model).items():
            for node, path in _walk(body['root']):
                values = node['attributes'].get('values', '')
                if _text(node, 'type') == 'daycycle:change' and 'sourceId($this.id)' in values:
                    node['attributes']['values'] = values.replace('sourceId($this.id)', 'sourceId($__object.id)')
                    report['controller_scope'].append(dict(quest=model['quest'], tree=tree, path=path))
        for document, payload in model['behavior_documents'].items():
            scope = document_scope(payload)
            strings = {v.get('name') for tree in payload['trees'].values() for v in tree['variables']
                       if v.get('type') in ('_string', 'string')}
            for name, tree in payload['trees'].items():
                local = {v.get('name'): v for v in tree['variables']}
                site = dict(quest=model['quest'], document=document, tree=name)
                for variable in tree['variables']:
                    initial = TIME_INITIALISER.fullmatch(variable.get('values') or '')
                    if variable.get('type') == 'additionalMoveParams' and initial:
                        variable['values'] = "%s('%s')" % (initial[1], initial[2])
                        report['initialisers'].append(dict(site, variable=variable['name'], source=initial[0]))

                def typed(match, attribute, path):
                    base, key = match[2], match[3]
                    if (local.get(base) or scope.get(base, {})).get('form') != 'associative' or key in strings:
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
                    for (op, attribute), values in VALUE_RENAMES.items():
                        if source_op == op and _text(node, attribute) in values:
                            report['value_renames'].append(dict(site, path=path, operation=op, attribute=attribute,
                                                                source=_text(node, attribute)))
                            node['attributes'][attribute] = '"' + values[_text(node, attribute)] + '"'
                    if source_op in BRANCHED and _text(node, 'failSubtMissing') in ('true', '1'):
                        branches = [child['op'] for child in node['children']]
                        if branches in (['Then'], ['Else']):
                            missing = _node('Else' if branches == ['Then'] else 'Then', [_node('Fail')])
                            missing['attributes'] = dict(canSkip='1')
                            node['children'] = sorted(node['children'] + [missing], key=lambda c: c['op'] != 'Then')
                            report['completed_branches'].append(dict(site, path=path, operation=source_op,
                                                                     added=missing['op']))
                    stand_in = source_op in STAND_INS
                    rule = STAND_INS[source_op][1] if stand_in else REWRITES[source_op][1] if source_op in REWRITES else (
                        _rename(source_op) if source_op in RENAMES else None)
                    if rule is None:
                        continue
                    try:
                        rewritten = rule(node)
                    except NotApplicable:
                        continue
                    except Blocked as error:
                        unmapped = sorted(set(node['attributes']) - set(RENAMES[source_op][1])) \
                            if source_op in RENAMES else []
                        report['rename_blocked'].append(dict(site, path=path, operation=source_op, unmapped=unmapped,
                                                             reason=str(error)))
                        continue
                    report['stand_ins' if stand_in else 'renamed'].append(
                        dict(site, path=path, source=source_op, target=rewritten['op']))
                    node.clear()
                    node.update(rewritten, source_op=source_op)
                    if stand_in:
                        node['stand_in'] = STAND_INS[source_op][0]
    report['rename_evidence'] = dict({source: entry[2] for source, entry in RENAMES.items()},
                                     **{source: ' '.join(entry[1].__doc__.split()) for source, entry in REWRITES.items()})
    report['stand_in_rules'] = {source: dict(target=entry[0], approved=entry[2], rule=' '.join(entry[1].__doc__.split()))
                                for source, entry in STAND_INS.items()}
    return models, report
