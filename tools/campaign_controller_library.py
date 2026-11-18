"""Stand-ins for three KCD1 library trees a controller includes (decisions 14 to 16).

Sean, 2026-11-17: "approve 14-16 use b for now and will see if we can fix
later". Each `IncludeTree` of one of these trees is replaced by the native
KCD2 function, never converted node by node. Every replaced site is a
declared stand-in: its row in the report names the KCD1 fields and behaviours
that are kept, approximated or dropped, so they can be restored later.

    final/dialogUtils.xml  dialogInitiator, dialogInitiator_instant      (14)
        -> Sequence[Expression(copies), Function_speech_polylogInitiator]
    final/sb_combat_fight.xml  fight, after its `t_fightOptions` Expression   (15)
        -> EntityContextElement(combat_forceUnarmed){Sequence[
               Function_combat_fightRepeated_template(target), rest of the sequence]}
    final/questUtils.xml  followNPC_inFormation                               (16)
        -> Sequence[Expression(formation.type), Function_moveInFormation_inFormation]

Evidence, retail KCD2 `Scripts.pak` (read by `native_evidence`, required at
conversion time; a name that is not there blocks the site):

14. `AI/speech/polyloginitiator.xml` declares alias, animationApproach, context,
    customParameters, metarole, participants, participantsMetaroles, preset
    (23 call sites carry exactly these eight). With `preset` `ignored` it takes
    `customParameters` whole (`AI/test/tv/so_test_dialog.xml`, 2 calls); with
    any other preset `customParameters` is never read. The caller's KCD1 record
    is converted as a script type of its own, so the fields both engines pass
    to `RequestDialog` are copied at run time into a variable of the native
    type `dialog:parameters:initiator`:

        KCD1 RequestDialog (dialogInitiator)      KCD2 RequestDialog (dialoginitiator_inner)
        Greeting   <- enableGreeting              Greeting   <- enableGreeting
        Ending     <- enableEnding                Ending     <- enableEnding
        UseTwins   <- useTwinsAsInitiator         UseTwins   <- useTwinsAsInitiator
        AllowPositioning <- allowPositioning      AllowPositioning <- movePlayer
        DisableRotations <- disableRotations      DisableRotations <- !rotatePlayer
        DisableRestrictions <- disableRestrictions DisableRestrictions <- !hideNearbyNpcs
        AnimationOverride <- defaultAnimState     AnimationOverride <- defaultAnimState,
                                                  which the function overwrites from
                                                  animationApproach (getanimationsetting.xml)

    `dialogInitiator_instant` passes only the first three and the animation
    state. KCD1 trees also write the alias as a bare word
    (`$t_dialogParameters.alias = q_skalitz_partyRunAway`), which KCD1 reads
    as a string; no retail KCD2 expression assigns a bare word, so the
    stand-in quotes it (and blocks when a variable of the tree has that name).
    `defaultAnimState` therefore has to be known when converting: the
    tree may assign it only in `OnInit`, one literal; unassigned it is KCD1's
    default `noOverride` (TypeDefinitions.xml).
15. `AI/world/sa_land.xml` `combat_fightRepeated_template(target)` raises
    `Function_callInterrupt_attack` on the NPC and returns. Retail forces fist
    fighting with the entity context `combat_forceUnarmed` (13 quest modules set
    it with `SetEntityContext`; one tree, `AI/quests/nebakovObrana`, with
    `EntityContextElement context="combat_forceUnarmed"`, the form used here).
    **Not proven offline:** that the context, held by a decorator of the tree
    that called the template, stays set while the attack interrupt runs.
16. `AI/move/moveUtils.xml` `moveInFormation_inFormation` is the same test as
    KCD1's `followNPC_inFormation` (`formation.leader == this` -> leader, else
    slave), on the same engine record `followFormationParams`, with the same
    lock name `followNPC_leader_<id>`; `_leader` and `_slave` are its two
    branches. It is chosen over them because who leads is a run-time value in
    both games. The native leader walks to `destination` instead of running a
    callback tree, and makes the formation `formation.type` without KCD1's
    fallback to `followNPC`, so the stand-in sets that name (the formation is
    defined in both games' FormationDefinitions.xml). A tree that names no
    leader callback passes `destination="$__null"` with followEnabled false and
    zero offsets, the retail form of `AI/quests/prepadeni`.

Nothing here defaults: a field of the KCD1 record with no entry in the tables
below, a use of the record the rules do not read, or a native name missing
from the evidence blocks the site with a `Library stand-in` reason.

Not runtime-verified. `IN_GAME_CHECKS` lists what only the game can answer.
"""
import re
import xml.etree.ElementTree as ET

from quest_import import literal

APPROVED = 'Sean, 2026-11-17 (first-hand): "approve 14-16 use b for now and will see if we can fix later"'
REASON = 'Library stand-in: '
INCLUDES = {('final/dialogutils.xml', 'dialogInitiator'): 'dialog',
            ('final/dialogutils.xml', 'dialogInitiator_instant'): 'dialog_instant',
            ('final/sb_combat_fight.xml', 'fight'): 'fight',
            ('final/questutils.xml', 'followNPC_inFormation'): 'formation'}
DECISIONS = dict(dialog=14, dialog_instant=14, fight=15, formation=16)
TARGETS = dict(dialog='Function_speech_polylogInitiator', dialog_instant='Function_speech_polylogInitiator',
               fight='Function_combat_fightRepeated_template', formation='Function_moveInFormation_inFormation')
# Field kinds for the behaviour compiler (campaign_controller_contracts.register adds them).
CONTRACTS = {
    'Function_speech_polylogInitiator': dict(
        alias='expression', animationApproach='value', context='value', customParameters='reference', metarole='value',
        participants='reference', participantsMetaroles='value', preset='value'),
    'Function_combat_fightRepeated_template': dict(target='reference'),
    'Function_moveInFormation_inFormation': dict(destination='reference', followEnabled='value',
                                                 followFormationParams='reference', pathOffset='value',
                                                 successDistance='value'),
    'EntityContextElement': dict(context='value'),
}
# The native record, declared under a name no KCD1 type has so the compiler maps it instead of converting it.
NATIVE_PARAMETERS = 'kcd2:dialog:parameters:initiator'
ENGINE_TYPES = {NATIVE_PARAMETERS: 'dialog:parameters:initiator'}
FUNCTIONS = {'speech_polylogInitiator': 'Function_speech_polylogInitiator',
             'combat_fightRepeated_template': 'Function_combat_fightRepeated_template',
             'moveInFormation_inFormation': 'Function_moveInFormation_inFormation'}

PARAMETERS, PARTICIPANTS, RESULT, NATIVE = 't_dialogParameters', 't_dialogParticipants', 't_dialogInitiator_result', 't_polylogParameters'
# KCD1 TypeDefinitions.xml, dialog:parameters and dialog:parameters:initiator (retail Scripts.pak).
DIALOG_DEFAULTS = dict(
    defaultAnimState='$enum:animationOverride.noOverride', animFragment='', animTag='', noTurnBody='false',
    noInterrupt='false', useTwinsAsReceiver='true', interruptSleepingOverride='false', isForcedDialog='false',
    enableGreeting='true', enableEnding='true', metarole='', topicId='0', alias='', lookAtId='', once='false',
    isInterruptibleByPlayer='true', moveToTarget='true', sendPrerequest='false', bruteForceDialogOnPlayer='false',
    useTwinsAsInitiator='true', waitOnReceiverDialogEnd='true', suspendRecievers='true', allowPositioning='true',
    dialogPreset='$enum:dialogPreset.default', disableRestrictions='false', disableRotations='false')
# field -> (native member, negated)
COPIED = dict(enableGreeting=('enableGreeting', False), enableEnding=('enableEnding', False),
              useTwinsAsInitiator=('useTwinsAsInitiator', False))
POSITIONING = dict(allowPositioning=('movePlayer', False), disableRotations=('rotatePlayer', True),
                   disableRestrictions=('hideNearbyNpcs', True))
APPROACH = {'$enum:animationOverride.userControlled': '$enum:animationApproach.dontPlayDialogAnimations',
            '$enum:animationOverride.dialogControlled': '$enum:animationApproach.tryDialogAnimations',
            '$enum:animationOverride.noOverride': '$enum:animationApproach.playDialogAnimationsIfFaderDialog'}
# What KCD1 did with a field the native function has no parameter for.
DROPPED = dict(
    moveToTarget='when true the initiator walks to the first receiver (Move, AlertedWalk) before the request; '
                 'the native function does not move',
    noTurnBody='when false (and moveToTarget true) the initiator steps in front of the receiver and turns '
               '(moveInfrontOfOpponent); the native record has turnBody, which no retail tree reads',
    waitOnReceiverDialogEnd='when true the initiator waits until no participant is in a dialogue; when false it '
                            'interrupts their dialogues (human:InterruptDialog); neither happens',
    suspendRecievers='when true the request is sent with SendMessage and the initiator waits for one '
                     'dialog:requestDone per NPC receiver, 1 minute at most; native RequestDialog has SendMessage false',
    bruteForceDialogOnPlayer='when true the player\'s dialogue is interrupted and fast travel stopped; when false '
                             'the request waits until the player has no threats and is out of combat',
    lookAtId='ForceLook at this entity while the dialogue runs',
    isInterruptibleByPlayer='RequestDialog IsInterruptibleByPlayer; the native node has no such field')
BARE = re.compile(r'[A-Za-z_]\w*')
UNREAD = dict(isForcedDialog='no tree of dialogUtils.xml reads it')
# A field the instant variant never reads is dead there, whatever the caller writes.
INSTANT_READS = {'alias', 'topicId', 'metarole', 'once', 'isInterruptibleByPlayer', 'useTwinsAsInitiator',
                 'enableGreeting', 'enableEnding', 'defaultAnimState', 'lookAtId'}
DIALOG_BEHAVIOURS = dict(
    dialog=['context suppression of greeting and farewell ($b_context suppressGreeting / suppressFarewell)',
            'dialogue animations switched off by script for userControlled (actor:SetDialogAnimationState)',
            'pairwise mutex between initiator and receiver (dialogSubtreeMutex_key) and the '
            'dialogSynchronization locks',
            'AllowSituations false while the tree runs',
            'placeBody message to a player receiver (the native function sends it only with preset fader)',
            'inDialog buff 053b4122 on the initiator while the dialogue runs',
            'DialogGate that holds the request until the initiator is in no dialogue',
            'the result written to t_dialogInitiator_result (a tree that names it is blocked)',
            'success and failure: KCD1 fails on receiver refusal, time-out or interruption; the native function '
            'returns what RequestDialog and DoDialog return'],
    dialog_instant=['the dialogSynchronization locks', 'ForceLook at lookAtId',
                    'movePlayer, rotatePlayer and hideNearbyNpcs keep the native defaults: KCD1 passes no '
                    'AllowPositioning, DisableRotations or DisableRestrictions here'])

FIGHT = 't_fightOptions'
FIGHT_REQUIRED = dict(combatRegimeOverride='$enum:combatTreeExecutionRegime.keepRunning',
                      preferredWeaponKind='$enum:weaponChange.unarmed')
FIGHT_DROPPED = dict(
    combatRegimeOverride='keepRunning: KCD1 fight runs until the surrounding tree ends it; the native template '
                         'raises the attack interrupt and returns, and nothing ends that interrupt with the tree',
    listener='the entity that receives combat events of this fight; no native parameter',
    preferredWeaponKind='unarmed: approximated by the entity context combat_forceUnarmed held over the call and '
                        'the rest of the sequence')
FIGHT_BEHAVIOURS = ['the KCD1 fight state machine (opponent selection, guard, block, sweet-spot movement, weapon '
                    'automation, morale and surrender handling of sb_combat_fight.xml): the native attack interrupt '
                    'decides all of it',
                    'combat:fightOptions fields left at their defaults (standStill, guardByDrawnWeapon, '
                    'combatBarkModificator, startInDefenseOnly, useMeleeShoutAutomation)']
UNARMED = 'combat_forceUnarmed'

FORMATION, MOVE, FORMATION_NAME = 't_followFormationParams', 't_distanceMove_params', 'followNPC'
FORMATION_PASSED = {'formation.leader', 'formation.preferedPosition', 'formation.policy', 'formation.allowRelocation'}
CALLBACK = {'leaderCallback.file': 'final/moveutils.xml', 'leaderCallback.tree': 'distancemove'}
MOVE_DROPPED = dict(speed='the leader runs distanceMove at this speed; the native leader moves at '
                          'formation.speedLimit, Walk when unset')
FORMATION_BEHAVIOURS = dict(
    leader=['distanceMove: horse use, light, rain speed-up, AllowSituations, stop distance and variation, '
            'destChangedThreshold; the native leader is one Move to the destination'],
    any=['follower movement: KCD1 runs Move (Walk) / SweetSpotFollower with formation.speedLimit under '
         'FollowFormation; native FormationFollower has no child and no speed limit',
         'formation.type: KCD1 falls back to followNPC when empty; the stand-in sets followNPC'])

IN_GAME_CHECKS = [
    dict(decision=14, check='An NPC-to-player dialogue started by the stand-in begins (e.g. Kunes after the fight, '
                            'the gate guard), and the quest moves on after it ends'),
    dict(decision=14, check='An NPC-to-NPC dialogue with NPC receivers begins (Matus with Fricek and Matej before '
                            'the pub) although no receiver is suspended and nobody sends dialog:requestDone'),
    dict(decision=14, check='Where KCD1 walked the initiator to the receiver (moveToTarget true), does the dialogue '
                            'start from where he stands, and from how far'),
    dict(decision=14, check='preset ignored with customParameters: greeting and ending follow the copied fields '
                            '(Blanka, Kunes sitting and the gate guard have both off); useTwinsAsInitiator is copied '
                            'as KCD1 has it (true unless a tree clears it), where retail KCD2 clears it for its '
                            'ingame and chat presets'),
    dict(decision=14, check='A dialogue whose alias KCD1 wrote as a bare word and the stand-in quoted starts '
                            '(Matus before the pub, the gate guard trialogue)'),
    dict(decision=14, check='blanka_givesBeer: the maintainer\'s quest-side ForcedDialog (campaign_dialogue_requests) '
                            'and this tree may both start q_skalitz_blankaGivesBeer'),
    dict(decision=15, check='The boys fight with fists: does combat_forceUnarmed held by the tree survive the attack '
                            'interrupt the template raises'),
    dict(decision=15, check='Does the attack interrupt (scheduled priority + 1) pre-empt the interrupt behaviour '
                            'that called it (priority 161), and does the brawl stop when that tree ends'),
    dict(decision=16, check='Matej and Fricek follow Matus in the followNPC formation to the skinner and release '
                            'when he arrives; Matus walks where KCD1 ran'),
]


class Blocked(ValueError):
    pass


def _text(node, name, default=''):
    return literal(node['attributes'].get(name, default))


def _node(op, children=(), **attributes):
    return dict(op=op, attributes={k: '"' + v + '"' for k, v in attributes.items()}, children=list(children), text='')


def _walk(node, path='Root', ancestors=()):
    yield node, path, ancestors
    for index, child in enumerate(node['children']):
        yield from _walk(child, path + '/' + str(index), ancestors + (node,))


def _include(node):
    if node['op'] != 'IncludeTree':
        return None
    return INCLUDES.get((_text(node, 'File').replace('\\', '/').lower(), _text(node, 'Name')))


# An attribute that is exactly a variable: where a search writes its result, and where a move reads its target.
SEARCH_OUTPUTS = {(op, attribute) for op in ('LinkDataFilter', 'LinkTagFilter', 'Nodalyzer', 'WUIDFilter')
                  for attribute in ('Parent', 'Child', 'Data')}
MOVE_INPUTS = {(op, attribute) for op in ('Move', 'ExactMove')
               for attribute in ('destinationSpecification', 'directionSpecification')}


def _uses(body, variable, outputs=()):
    """Every write of a record in a tree: [(member, value, in OnInit, path)], or Blocked.

    Read are `$variable.member = value` statements of an Expression and, for a
    member listed in `outputs`, a search that writes its result there. A move
    that reads a member as its target is not a write. Any other mention
    blocks: the rules would not know what it does.
    """
    found, name = [], re.compile(r'(?<![\w.])\$?' + re.escape(variable) + r'\b')
    statement = re.compile(r'\$' + re.escape(variable) + r'\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*=(?!=)\s*(.*)', re.S)
    init = {index for index, child in enumerate(body['root']['children']) if child['op'] == 'OnInit'}
    for node, path, _ in _walk(body['root']):
        if node.get('library_copy'):
            continue  # a node a stand-in of this tree already wrote
        steps = path.split('/')
        in_init = len(steps) > 1 and int(steps[1]) in init
        for attribute, raw in node['attributes'].items():
            value = literal(raw)
            if not name.search(value):
                continue
            if node['op'] == 'Expression' and attribute == 'expressions':
                for part in re.split(r'\n', value):
                    part = part.strip().rstrip(',').strip()
                    if not name.search(part):
                        continue
                    match = statement.fullmatch(part)
                    if not match or name.search(match[2]):
                        raise Blocked('%s is used in a statement the rule does not read: %s' % (variable, part[:80]))
                    found.append((match[1], match[2].strip(), in_init, path))
            elif (node['op'], attribute) in SEARCH_OUTPUTS and value.removeprefix('$').startswith(variable + '.') \
                    and value.removeprefix('$').removeprefix(variable + '.') in outputs:
                found.append((value.removeprefix('$').removeprefix(variable + '.'), '<search result>', in_init, path))
            elif (node['op'], attribute) in MOVE_INPUTS and re.fullmatch(
                    r'\$?' + re.escape(variable) + r'(?:\.[A-Za-z_]\w*)+', value):
                continue
            else:
                raise Blocked('%s is used outside an assignment: %s %s' % (variable, node['op'], attribute))
    return found


def _declared(body, name, kind, form='single'):
    found = [v for v in body['variables'] if v.get('name') == name]
    if len(found) != 1 or found[0].get('type') != kind or found[0].get('form', 'single') != form:
        raise Blocked('the tree does not declare %s as %s (%s)' % (name, kind, form))


def _need(native, group, name):
    if name not in native.get(group, ()):
        raise Blocked('native %s is not in retail KCD2: %s' % (group.rstrip('s').replace('_', ' '), name))


def _parameters(native, op, attributes):
    function = next(name for name, node in FUNCTIONS.items() if node == op)
    _need(native, 'functions', function)
    missing = sorted(set(attributes) - set(native['functions'][function]))
    if missing:
        raise Blocked('native function %s declares no parameter %s' % (function, ', '.join(missing)))


def _field_rows(uses, defaults, handled):
    """One row per member the caller assigns or the stand-in drops, with the values in effect."""
    rows, by_field = [], {}
    for member, value, in_init, path in uses:
        by_field.setdefault(member, []).append(dict(value=value, path=path, on_init=in_init))
    for member in sorted(set(by_field) | {m for m, how in handled.items() if how[0] == 'dropped'}):
        how = handled[member]
        rows.append(dict(field=member, handling=how[0], native=how[1], effect=how[2],
                         assigned=by_field.get(member, []), kcd1_default=defaults.get(member)))
    return rows


def _dialog(variant, tree, body, node, path, ancestors, native, formations):
    instant = variant == 'dialog_instant'
    if set(node['attributes']) - {'File', 'Name', 'nodeLabel', 'saveVersion'} or node['children']:
        raise Blocked('the include carries fields or children')
    _declared(body, PARAMETERS, 'dialog:parameters:initiator')
    _declared(body, PARTICIPANTS, 'common:wuid', 'array')
    if any(RESULT in literal(raw) for n, _, _ in _walk(body['root']) for raw in n['attributes'].values()) \
            or any(v.get('name') == RESULT for v in body['variables']):
        raise Blocked('the tree reads ' + RESULT + ', which the native function does not write')
    uses = _uses(body, PARAMETERS)
    handled = {}
    for member in set(DIALOG_DEFAULTS):
        if member == 'alias':
            handled[member] = ('parameter', 'alias', 'passed as written at run time')
        elif member in COPIED or (member in POSITIONING and not instant):
            target, negated = (COPIED.get(member) or POSITIONING[member])
            handled[member] = ('copied', ('!' if negated else '') + 'customParameters.' + target, 'copied at run time')
        elif member == 'defaultAnimState':
            handled[member] = ('static', 'animationApproach', 'read from the tree when converting')
        elif instant and member not in INSTANT_READS:
            handled[member] = ('unread', None, 'dialogInitiator_instant does not read it')
        elif member in UNREAD:
            handled[member] = ('unread', None, UNREAD[member])
        elif member in DROPPED:
            handled[member] = ('dropped', None, DROPPED[member])
    for member, value, _, path in uses:
        if member not in handled:
            raise Blocked('%s.%s has no declared handling (assigned at %s)' % (PARAMETERS, member, path))
    quoted = []
    for member, value, _, where in uses:
        if member == 'alias' and BARE.fullmatch(value) and value not in ('true', 'false'):
            if any(v.get('name') == value for v in body['variables']):
                raise Blocked('the alias is a bare word that is also a variable of the tree: ' + value)
            quoted.append((where, value))
    states = [(value, in_init) for member, value, in_init, _ in uses if member == 'defaultAnimState']
    if any(not in_init for _, in_init in states) or len({value for value, _ in states}) > 1:
        raise Blocked('defaultAnimState is assigned outside OnInit or to more than one value')
    state = states[0][0] if states else DIALOG_DEFAULTS['defaultAnimState']
    if state not in APPROACH:
        raise Blocked('defaultAnimState has no animationApproach: ' + state)
    existing = [v for v in body['variables'] if v.get('name') == NATIVE]
    if existing and existing[0].get('type') != NATIVE_PARAMETERS:
        raise Blocked('the tree already has a variable named ' + NATIVE)
    copies = dict(COPIED, **({} if instant else POSITIONING))
    attributes = dict(alias='$%s.alias' % PARAMETERS, animationApproach=APPROACH[state], context='$__null',
                      customParameters='$' + NATIVE, metarole='', participants='$' + PARTICIPANTS,
                      participantsMetaroles='', preset='$enum:dialogPreset.ignored')
    _parameters(native, TARGETS[variant], attributes)
    _need(native, 'literals', attributes['animationApproach'])
    _need(native, 'literals', attributes['preset'])
    for target, _ in copies.values():
        _need(native, 'dialog_fields', target)
    if not existing:
        body['variables'].append(dict(name=NATIVE, type=NATIVE_PARAMETERS, values='', form='single'))
    by_path = {where: n for n, where, _ in _walk(body['root'])}
    for where, value in quoted:
        target = by_path[where]['attributes']
        target['expressions'] = re.sub(r'(\$' + PARAMETERS + r'\.alias\s*=\s*)' + re.escape(value) + r"(?![\w.'])",
                                       lambda m: m[1] + "'" + value + "'", target['expressions'])
    uses = [(m, "'" + v + "'" if m == 'alias' and (w, v) in quoted else v, i, w) for m, v, i, w in uses]
    expression = '\n'.join('$%s.%s = %s$%s.%s' % (NATIVE, target, '!' if negated else '', PARAMETERS, member)
                           for member, (target, negated) in copies.items())
    call = _node(TARGETS[variant], **attributes)
    new = _node('Sequence', [_node('Expression', expressions=expression), call])
    row = dict(fields=_field_rows(uses, DIALOG_DEFAULTS, handled), behaviours_dropped=DIALOG_BEHAVIOURS[variant],
               animation=dict(kcd1=state, native=APPROACH[state], assigned=bool(states)),
               variable=dict(name=NATIVE, type=ENGINE_TYPES[NATIVE_PARAMETERS]),
               alias_quoted=[dict(path=where, alias=value) for where, value in quoted])
    return new, [new, new['children'][0], call], row, None


def _fight(variant, tree, body, node, path, ancestors, native, formations):
    parent = ancestors[-1] if ancestors else None
    if set(node['attributes']) - {'File', 'Name', 'nodeLabel', 'saveVersion'} or node['children']:
        raise Blocked('the include carries fields or children')
    if parent is None or parent['op'] != 'Sequence':
        raise Blocked('fight is not a step of a sequence')
    index = next(i for i, child in enumerate(parent['children']) if child is node)
    options = parent['children'][index - 1] if index else None
    if options is None or options['op'] != 'Expression' or set(options['attributes']) - {'expressions', 'saveVersion'}:
        raise Blocked('fight is not preceded by the Expression that sets ' + FIGHT)
    rest = parent['children'][index + 1:]
    if not rest:
        raise Blocked('nothing follows fight in its sequence: the native call returns at once and nothing would '
                      'hold the unarmed context')
    _declared(body, FIGHT, 'combat:fightOptions')
    uses = _uses(body, FIGHT)
    here = [(member, value) for member, value, _, _ in uses]
    statements = [part.strip().rstrip(',').strip() for part in _text(options, 'expressions').split('\n')]
    before = path.rsplit('/', 1)[0] + '/' + str(index - 1)
    if any(where != before for _, _, _, where in uses) or len(here) != len([s for s in statements if s]) \
            or len({member for member, _ in here}) != len(here):
        raise Blocked(FIGHT + ' is assigned elsewhere in the tree, twice, or beside other statements')
    fields = dict(here)
    unknown = sorted(set(fields) - {'opponent', 'listener'} - set(FIGHT_REQUIRED))
    if unknown:
        raise Blocked('%s.%s has no declared handling' % (FIGHT, unknown[0]))
    for member, wanted in FIGHT_REQUIRED.items():
        if fields.get(member) != wanted:
            raise Blocked('%s.%s is %s; only %s has a stand-in' % (FIGHT, member, fields.get(member, 'not set'), wanted))
    if not re.fullmatch(r'\$[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', fields.get('opponent', '')):
        raise Blocked(FIGHT + '.opponent is not a variable')
    if fields.get('listener', '$this.id') != '$this.id':
        raise Blocked(FIGHT + '.listener is another entity')
    call = _node(TARGETS[variant], target=fields['opponent'])
    _parameters(native, call['op'], ['target'])
    _need(native, 'entity_contexts', UNARMED)
    held = _node('Sequence', [call] + rest)
    new = _node('EntityContextElement', [held], context=UNARMED)
    handled = dict(opponent=('parameter', 'target', 'passed as written'),
                   **{m: ('dropped' if m != 'preferredWeaponKind' else 'approximated',
                          'EntityContextElement ' + UNARMED if m == 'preferredWeaponKind' else None, FIGHT_DROPPED[m])
                      for m in FIGHT_DROPPED if m in fields})
    row = dict(fields=[dict(field=m, handling=handled[m][0], native=handled[m][1], effect=handled[m][2],
                            assigned=[dict(value=fields[m])], kcd1_default=None) for m in sorted(fields)],
               behaviours_dropped=FIGHT_BEHAVIOURS, unarmed=dict(context=UNARMED, proven_offline=False),
               held=[child['op'] for child in rest])
    # The options Expression is consumed: its four statements are the row above.
    return new, [new, held, call], row, (parent, index - 1)


def _formation(variant, tree, body, node, path, ancestors, native, formations):
    if set(node['attributes']) - {'File', 'Name', 'nodeLabel', 'saveVersion'} or node['children']:
        raise Blocked('the include carries fields or children')
    _declared(body, FORMATION, 'followFormationParams')
    uses = _uses(body, FORMATION, outputs={'formation.leader'})
    members = {member for member, _, _, _ in uses}
    unknown = sorted(members - FORMATION_PASSED - set(CALLBACK))
    if unknown:
        raise Blocked('%s.%s has no declared handling' % (FORMATION, unknown[0]))
    callback = {member: value for member, value, in_init, _ in uses if member in CALLBACK}
    fields = [dict(field=member, handling='passed', native='followFormationParams.' + member,
                   effect='the same member of the engine record', assigned=[dict(value=value, path=path, on_init=in_init)],
                   kcd1_default=None) for member, value, in_init, path in uses if member in FORMATION_PASSED]
    behaviours = list(FORMATION_BEHAVIOURS['any'])
    if callback:
        if any(not in_init for member, _, in_init, _ in uses if member in CALLBACK) \
                or {m: v.strip("'").lower() for m, v in callback.items()} != CALLBACK \
                or sum(member in CALLBACK for member, _, _, _ in uses) != len(CALLBACK):
            raise Blocked('the leader callback is not distanceMove of final/moveUtils.xml, set once in OnInit')
        if not any(v.get('name') == MOVE for v in body['variables']):
            raise Blocked('the tree does not declare ' + MOVE)
        move = _uses(body, MOVE, outputs={'target'})
        if any(not in_init for _, _, in_init, _ in move):
            raise Blocked(MOVE + ' is assigned outside OnInit')
        values = {}
        for member, value, _, _ in move:
            if member in values:
                raise Blocked('%s.%s is assigned twice' % (MOVE, member))
            values[member] = value
        unknown = sorted(set(values) - {'target', 'movementTargetType'} - set(MOVE_DROPPED))
        if unknown:
            raise Blocked('%s.%s has no declared handling' % (MOVE, unknown[0]))
        if values.get('movementTargetType') != '$enum:movementTargetType.wuid' or 'target' not in values:
            raise Blocked('distanceMove is not given an entity target')
        destination = '$%s.target' % MOVE
        fields += [dict(field='leaderCallback (distanceMove)', handling='approximated', native='destination',
                        effect='the native leader moves to the callback\'s target itself',
                        assigned=[dict(value=v) for v in callback.values()], kcd1_default=None)]
        fields += [dict(field=MOVE + '.' + member, handling='dropped', native=None, effect=MOVE_DROPPED[member],
                        assigned=[dict(value=values[member])], kcd1_default=None)
                   for member in sorted(values) if member in MOVE_DROPPED]
        behaviours = FORMATION_BEHAVIOURS['leader'] + behaviours
    else:
        destination = '$__null'
    name = FORMATION_NAME
    if name not in native.get('formations', {}):
        raise Blocked('native formation is not in retail KCD2: ' + name)
    if name not in (formations or {}):
        raise Blocked('KCD1 formation is not in the source definitions: ' + name)
    attributes = dict(destination=destination, followEnabled='false', followFormationParams='$' + FORMATION,
                      pathOffset='0.000000', successDistance='0.000000')
    _parameters(native, TARGETS[variant], attributes)
    call = _node(TARGETS[variant], **attributes)
    new = _node('Sequence', [_node('Expression', expressions="$%s.formation.type = '%s'" % (FORMATION, name)), call])
    row = dict(fields=fields, behaviours_dropped=behaviours, role='leader callback named' if callback else 'no callback',
               formation=dict(name=name, kcd1_spots=formations[name], kcd2_spots=native['formations'][name],
                              spots_equal=formations[name] == native['formations'][name]))
    return new, [new, new['children'][0], call], row, None


RULES = dict(dialog=_dialog, dialog_instant=_dialog, fight=_fight, formation=_formation)


def rules():
    """Entries for the report's stand-in registry (`stand_in_rules`), keyed by the include they replace."""
    return {'IncludeTree %s:%s' % (file, name): dict(target=TARGETS[variant], approved=APPROVED,
                                                     decision=DECISIONS[variant],
                                                     rule=' '.join(__doc__.split('\n\n')[0].split()))
            for (file, name), variant in INCLUDES.items()}


def apply(model, native, formations=None, skip=()):
    """Replace the library includes of the controller in place; return the report.

    `native` is `native_evidence(...)`, `formations` the KCD1 definitions
    (`formation_spots`), `skip` trees another converter owns. Call `finish`
    after the other source passes: they may move or rewrite the new nodes.
    """
    own = 'libs/ai/quests/' + model['quest'].lower() + '.xml'
    trees = model['behavior_documents'].get(own, dict(trees={}))['trees']
    report = dict(quest=model['quest'], approved=APPROVED, sites=[], left=[], stand_ins=[],
                  in_game_checks=IN_GAME_CHECKS, runtime_verified=False, _refs=[])
    for tree, body in trees.items():
        if tree in skip:
            continue
        changed = True
        while changed:
            changed = False
            for node, path, ancestors in _walk(body['root']):
                variant = _include(node)
                if variant is None or node.get('library_left'):
                    continue
                include = '%s:%s' % (_text(node, 'File'), _text(node, 'Name'))
                try:
                    new, nodes, row, consumed = RULES[variant](variant, tree, body, node, path, ancestors, native, formations)
                except Blocked as error:
                    node['library_left'] = True
                    node.setdefault('blocked', []).append(REASON + str(error))
                    report['left'].append(dict(tree=tree, path=path, include=include, reason=str(error)))
                    continue
                row = dict(tree=tree, path=path, include=include, decision=DECISIONS[variant], target=TARGETS[variant],
                           approved=APPROVED, **row)
                for made in nodes:
                    made['library_copy'] = True
                if consumed:
                    parent, start = consumed
                    parent['children'][start:] = [new]
                    new.update(source_op='IncludeTree', stand_in=TARGETS[variant])
                else:
                    node.clear()
                    node.update(new, source_op='IncludeTree', stand_in=TARGETS[variant])
                    nodes[0] = node
                report['sites'].append(row)
                report['_refs'].append((row, body, nodes))
                changed = True
                break
    for body in trees.values():
        for node, _, _ in _walk(body['root']):
            node.pop('library_left', None)
            node.pop('library_copy', None)
    return finish(report, final=False)


def finish(report, final=True):
    """Write each site's path and emitted nodes from the tree as it now stands."""
    for row, body, nodes in report['_refs']:
        paths = {id(node): path for node, path, _ in _walk(body['root'])}
        missing = [node['op'] for node in nodes if id(node) not in paths]
        if missing:
            raise ValueError('A later pass removed a library stand-in node: ' + ', '.join(missing))
        row['path'] = paths[id(nodes[0])]
        row['nodes'] = [dict(path=paths[id(node)], op=node['op'],
                             attributes={k: literal(v) for k, v in sorted(node['attributes'].items())}) for node in nodes]
    report['stand_ins'] = [dict(tree=row['tree'], path=row['path'], source='IncludeTree ' + row['include'].rsplit(':', 1)[-1],
                                target=row['target']) for row in report['sites']]
    if final:
        del report['_refs']
    return report


def check(report, emitted):
    """Compare the emitted trees with the declared nodes of each site; return {tree: [problem]}.

    `emitted` is {tree name: emitted Root element}. A site whose tree is not
    emitted is not compared.
    """
    problems = {}
    for row in report['sites']:
        root = emitted.get(row['tree'])
        if root is None:
            continue
        for declared in row['nodes']:
            element = root
            try:
                for step in declared['path'].split('/')[1:]:
                    element = element[int(step)]
            except IndexError:
                problems.setdefault(row['tree'], []).append(declared['path'] + ': stand-in node is not emitted')
                continue
            if element.tag != declared['op'] or dict(element.attrib) != declared['attributes']:
                problems.setdefault(row['tree'], []).append('%s: emitted %s %s, declared %s %s' % (
                    declared['path'], element.tag, dict(sorted(element.attrib.items())), declared['op'],
                    declared['attributes']))
    return problems


def supplement(catalog, native):
    """Add the stand-in functions retail defines but calls only outside a runtime Root.

    The compiler's catalog reads runtime Roots. `combat_fightRepeated_template`
    is defined in `AI/world/sa_land.xml` (`is_function="1"`, parameter
    `target`) and its one call, `AI/quests/zakopanyZitrek`, sits in a
    ForestContainer. The node is entered with the parameters the definition
    declares; a function retail does not define is not added.
    """
    for function, op in FUNCTIONS.items():
        if function in native.get('functions', {}) and op not in catalog['nodes']:
            catalog['nodes'][op] = dict(attributes=sorted(native['functions'][function]), children=[],
                                        example='function definition ' + function + ' (no call in a runtime Root)')
    return catalog


def formation_spots(data):
    """{name: [[spot name, x, y, radius]]} of a FormationDefinitions.xml."""
    return {formation.get('name'): [[s.get('name'), s.get('x'), s.get('y'), s.get('radius')] for s in formation.iter('Spot')]
            for formation in ET.fromstring(data).iter('Formation')}


def native_evidence(archive):
    """What retail KCD2 `Scripts.pak` (an open ZipFile) says about the names the stand-ins write."""
    functions, literals, fields, contexts, formations = {}, set(), set(), set(), {}
    for entry in archive.namelist():
        low = entry.lower()
        if not low.startswith('ai/') or not low.endswith('.xml'):
            continue
        data = archive.read(entry)
        if low == 'ai/formationdefinitions.xml':
            formations = formation_spots(data)
            continue
        text = data.decode('utf-8', 'replace')
        literals.update(re.findall(r'\$enum:(?:dialogPreset|animationApproach)\.[A-Za-z_]\w*', text))
        contexts.update(re.findall(r'<EntityContextElement context="([A-Za-z_]\w*)"', text))
        if low.startswith('ai/speech/'):
            fields.update(re.findall(r'\$(?:dialogParameters|customParameters)\.([A-Za-z_]\w*)', text))
        if any(('name="%s"' % name) in text for name in FUNCTIONS):
            for tree in ET.fromstring(data).iter('BehaviorTree'):
                if tree.get('name') in FUNCTIONS and tree.get('is_function') == '1':
                    functions[tree.get('name')] = sorted(v.get('name') for v in tree.findall('./Parameters/Variable'))
    return dict(functions=functions, literals=sorted(literals), dialog_fields=sorted(fields),
                entity_contexts=sorted(contexts), formations=formations)
