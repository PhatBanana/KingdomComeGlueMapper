"""Converter C2: native stand-ins for the library trees a controller includes (decisions 14 to 16).

Every rule is paired with mutations: the same tree with one field, use or
piece of native evidence changed must be left as an include and blocked with
a `Library stand-in` reason, never converted with a default.
"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_controller_contracts as contracts
import campaign_controller_library as library

KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
RETAIL = (KCD1 / 'Data/Scripts.pak').is_file() and (KCD2 / 'Data/Scripts.pak').is_file()
OWN = 'libs/ai/quests/q_example.xml'
SPOTS = [['left', '-0.7', '1.7', '0.5'], ['right', '0.7', '1.7', '0.5']]
NATIVE = dict(
    functions={'speech_polylogInitiator': ['alias', 'animationApproach', 'context', 'customParameters', 'metarole',
                                           'participants', 'participantsMetaroles', 'preset'],
               'combat_fightRepeated_template': ['target'],
               'moveInFormation_inFormation': ['destination', 'followEnabled', 'followFormationParams', 'pathOffset',
                                               'successDistance']},
    literals=['$enum:dialogPreset.ignored', '$enum:animationApproach.dontPlayDialogAnimations',
              '$enum:animationApproach.tryDialogAnimations', '$enum:animationApproach.playDialogAnimationsIfFaderDialog'],
    dialog_fields=['alias', 'enableGreeting', 'enableEnding', 'useTwinsAsInitiator', 'movePlayer', 'rotatePlayer',
                   'hideNearbyNpcs'],
    entity_contexts=['combat_forceUnarmed'], formations={'followNPC': SPOTS})
PARAMETERS = dict(name='t_dialogParameters', type='dialog:parameters:initiator', values='', form='single')
PARTICIPANTS = dict(name='t_dialogParticipants', type='common:wuid', values='', form='array')
OPTIONS = dict(name='t_fightOptions', type='combat:fightOptions', values='', form='single')
FORMATION = dict(name='t_followFormationParams', type='followFormationParams', values='', form='single')
MOVE = dict(name='t_distanceMove_params', type='distanceMove_params:wuid', values='', form='single')


def q(value):
    return '"' + value + '"'


def node(op, children=(), **attributes):
    return dict(op=op, attributes={k: q(v) for k, v in attributes.items()}, children=list(children), text='')


def include(name, file='final/dialogUtils.xml'):
    return node('IncludeTree', File=file, Name=name)


def expression(*statements):
    return node('Expression', expressions=', \n'.join(statements) + ',')


def model(behavior, variables, init=()):
    root = node('Root', [node('OnInit', copy.deepcopy(list(init))), node('Behavior', copy.deepcopy(list(behavior)))])
    return dict(quest='q_example', behavior_documents={OWN: dict(trees=dict(
        main=dict(variables=[dict(v) for v in variables], root=root)))})


def run(behavior, variables, init=(), native=NATIVE, formations=None, **kwargs):
    source = model(behavior, variables, init)
    report = library.finish(library.apply(source, native, {'followNPC': SPOTS} if formations is None else formations, **kwargs))
    json.dumps(report)  # the report is data
    return source['behavior_documents'][OWN]['trees']['main'], report


def at(tree, path):
    found = tree['root']
    for step in path.split('/')[1:]:
        found = found['children'][int(step)]
    return found


def without(group, name):
    native = copy.deepcopy(NATIVE)
    if isinstance(native[group], dict): del native[group][name]
    else: native[group].remove(name)
    return native


def field(site, name):
    return next(row for row in site['fields'] if row['field'] == name)


DIALOG = [PARAMETERS, PARTICIPANTS]
CALL = dict(alias='$t_dialogParameters.alias', animationApproach='$enum:animationApproach.playDialogAnimationsIfFaderDialog',
            context='$__null', customParameters='$t_polylogParameters', metarole='', participants='$t_dialogParticipants',
            participantsMetaroles='', preset='$enum:dialogPreset.ignored')


class DialogTests(unittest.TestCase):
    def assert_left(self, behavior, variables, text, init=(), **kwargs):
        tree, report = run(behavior, variables, init, **kwargs)
        left = [n for n in self.walk(tree['root']) if n['op'] == 'IncludeTree']
        self.assertEqual((len(report['sites']), len(report['left']), len(left)), (0, 1, 1), text)
        self.assertIn(text, report['left'][0]['reason'])
        self.assertEqual(left[0]['blocked'], [library.REASON + report['left'][0]['reason']])
        self.assertEqual(report['stand_ins'], [])
        return tree, report

    def walk(self, root):
        yield root
        for child in root['children']: yield from self.walk(child)

    def test_the_include_becomes_the_native_call_with_the_fields_both_engines_pass(self):
        tree, report = run([node('Sequence', [
            expression("$t_dialogParticipants[0] = $__player", "$t_dialogParameters.alias = 'q_example_talk'",
                       '$t_dialogParameters.enableGreeting = false', '$t_dialogParameters.moveToTarget = false',
                       '$t_dialogParameters.isForcedDialog = true'),
            include('dialogInitiator')])], DIALOG)
        site, = report['sites']
        stand_in = at(tree, 'Root/1/0/1')
        self.assertEqual((site['path'], site['decision'], site['target']), ('Root/1/0/1', 14, 'Function_speech_polylogInitiator'))
        self.assertEqual((stand_in['op'], stand_in['source_op'], stand_in['stand_in']),
                         ('Sequence', 'IncludeTree', 'Function_speech_polylogInitiator'))
        copies, call = stand_in['children']
        self.assertEqual(copies['attributes']['expressions'], q(
            '$t_polylogParameters.enableGreeting = $t_dialogParameters.enableGreeting\n'
            '$t_polylogParameters.enableEnding = $t_dialogParameters.enableEnding\n'
            '$t_polylogParameters.useTwinsAsInitiator = $t_dialogParameters.useTwinsAsInitiator\n'
            '$t_polylogParameters.movePlayer = $t_dialogParameters.allowPositioning\n'
            '$t_polylogParameters.rotatePlayer = !$t_dialogParameters.disableRotations\n'
            '$t_polylogParameters.hideNearbyNpcs = !$t_dialogParameters.disableRestrictions'))
        self.assertEqual((call['op'], call['attributes']), ('Function_speech_polylogInitiator', {k: q(v) for k, v in CALL.items()}))
        self.assertEqual(set(call['attributes']), set(library.CONTRACTS['Function_speech_polylogInitiator']))
        self.assertEqual(tree['variables'][-1], dict(name='t_polylogParameters', type=library.NATIVE_PARAMETERS, values='', form='single'))
        self.assertEqual([n['path'] for n in site['nodes']], ['Root/1/0/1', 'Root/1/0/1/0', 'Root/1/0/1/1'])
        self.assertEqual(site['nodes'][2]['attributes'], CALL)
        self.assertEqual(report['stand_ins'], [dict(tree='main', path='Root/1/0/1', source='IncludeTree dialogInitiator',
                                                    target='Function_speech_polylogInitiator')])
        # What is not carried is listed with the value in effect: assigned, or KCD1's default.
        self.assertEqual((field(site, 'moveToTarget')['handling'], field(site, 'moveToTarget')['assigned'][0]['value'],
                          field(site, 'moveToTarget')['kcd1_default']), ('dropped', 'false', 'true'))
        self.assertEqual((field(site, 'suspendRecievers')['handling'], field(site, 'suspendRecievers')['assigned'],
                          field(site, 'suspendRecievers')['kcd1_default']), ('dropped', [], 'true'))
        self.assertEqual({f['field'] for f in site['fields'] if f['handling'] == 'dropped'}, set(library.DROPPED))
        self.assertEqual(field(site, 'isForcedDialog')['handling'], 'unread')
        self.assertEqual((field(site, 'enableGreeting')['handling'], field(site, 'enableGreeting')['native']),
                         ('copied', 'customParameters.enableGreeting'))
        self.assertEqual(site['animation'], dict(kcd1='$enum:animationOverride.noOverride', assigned=False,
                                                 native='$enum:animationApproach.playDialogAnimationsIfFaderDialog'))
        self.assertTrue(site['behaviours_dropped'])

    def test_the_instant_variant_copies_only_what_it_passes_and_ignores_what_it_never_reads(self):
        tree, report = run([node('Sequence', [
            expression("$t_dialogParameters.alias = 'q_example_talk'", '$t_dialogParameters.bruteForceDialogOnPlayer = true'),
            include('dialogInitiator_instant')])], DIALOG)
        site, = report['sites']
        self.assertEqual(at(tree, 'Root/1/0/1/0')['attributes']['expressions'].count('\n'), 2)
        self.assertNotIn('movePlayer', at(tree, 'Root/1/0/1/0')['attributes']['expressions'])
        self.assertEqual(field(site, 'bruteForceDialogOnPlayer')['handling'], 'unread')
        self.assertEqual({f['field'] for f in site['fields'] if f['handling'] == 'dropped'}, {'lookAtId', 'isInterruptibleByPlayer'})

    def test_a_bare_word_alias_is_quoted_unless_a_variable_has_its_name(self):
        steps = [node('Sequence', [expression('$t_dialogParameters.alias = q_example_talk', '$t_dialogParameters.moveToTarget = false'),
                                   include('dialogInitiator')])]
        tree, report = run(steps, DIALOG)
        self.assertEqual(at(tree, 'Root/1/0/0')['attributes']['expressions'],
                         q("$t_dialogParameters.alias = 'q_example_talk', \n$t_dialogParameters.moveToTarget = false,"))
        self.assertEqual(report['sites'][0]['alias_quoted'], [dict(path='Root/1/0/0', alias='q_example_talk')])
        self.assertEqual(field(report['sites'][0], 'alias')['assigned'][0]['value'], "'q_example_talk'")
        self.assert_left(steps, DIALOG + [dict(name='q_example_talk', type='_string', values='', form='single')], 'bare word')

    def test_two_includes_of_one_tree_share_the_native_record(self):
        tree, report = run([node('Sequence', [include('dialogInitiator'), include('dialogInitiator_instant')])], DIALOG)
        self.assertEqual([s['path'] for s in report['sites']], ['Root/1/0/0', 'Root/1/0/1'])
        self.assertEqual([v['name'] for v in tree['variables']].count('t_polylogParameters'), 1)
        self.assertFalse(any('library_copy' in n or 'library_left' in n for n in self.walk(tree['root'])))

    def test_the_animation_state_is_read_from_on_init_only(self):
        state = expression('$t_dialogParameters.defaultAnimState = $enum:animationOverride.userControlled')
        tree, report = run([include('dialogInitiator')], DIALOG, init=[state])
        self.assertEqual(at(tree, 'Root/1/0/1')['attributes']['animationApproach'],
                         q('$enum:animationApproach.dontPlayDialogAnimations'))
        self.assertEqual(report['sites'][0]['animation']['assigned'], True)
        self.assert_left([node('Sequence', [state, include('dialogInitiator')])], DIALOG, 'outside OnInit')
        other = expression('$t_dialogParameters.defaultAnimState = $enum:animationOverride.dialogControlled')
        self.assert_left([include('dialogInitiator')], DIALOG, 'more than one value', init=[state, other])
        self.assert_left([include('dialogInitiator')], DIALOG, 'no animationApproach',
                         init=[expression('$t_dialogParameters.defaultAnimState = $state')])

    def test_a_field_or_use_without_declared_handling_blocks_the_site(self):
        for statement, text in (("$t_dialogParameters.metarole = 'GOSSIP'", 'metarole has no declared handling'),
                                ('$t_dialogParameters.dialogPreset = $enum:dialogPreset.forcedOnPlayer', 'dialogPreset has no declared'),
                                ('$t_dialogParameters.once = true', 'once has no declared'),
                                ('$t_dialogParameters.madeUp = 1', 'madeUp has no declared'),
                                ('$t_dialogParameters = $other', 'statement the rule does not read'),
                                ('$other = $t_dialogParameters.alias', 'statement the rule does not read')):
            self.assert_left([node('Sequence', [expression(statement), include('dialogInitiator')])], DIALOG, text)
        copy_node = node('VarOperation', varName='t_dialogParameters', targetVarName='saved', operation='Copy', argument='')
        self.assert_left([node('Sequence', [copy_node, include('dialogInitiator')])], DIALOG, 'used outside an assignment')
        result = dict(name='t_dialogInitiator_result', type='enum:dialogResult', values='', form='single')
        self.assert_left([include('dialogInitiator')], DIALOG + [result], 't_dialogInitiator_result')
        self.assert_left([include('dialogInitiator')], [PARTICIPANTS], 'does not declare t_dialogParameters')
        self.assert_left([include('dialogInitiator')], [dict(PARAMETERS, type='dialog:parameters'), PARTICIPANTS], 'does not declare')
        self.assert_left([include('dialogInitiator')], [PARAMETERS, dict(PARTICIPANTS, form='single')], 'does not declare')
        self.assert_left([include('dialogInitiator')], DIALOG + [dict(name='t_polylogParameters', type='_int', values='', form='single')],
                         'already has a variable')
        self.assert_left([dict(include('dialogInitiator'), children=[node('Success')])], DIALOG, 'fields or children')

    def test_a_native_name_missing_from_retail_blocks_the_site(self):
        for native, text in ((without('functions', 'speech_polylogInitiator'), 'native function is not in retail KCD2'),
                             (without('literals', '$enum:dialogPreset.ignored'), 'native literal is not in retail KCD2'),
                             (without('dialog_fields', 'movePlayer'), 'native dialog field is not in retail KCD2: movePlayer'),
                             (dict(NATIVE, functions=dict(NATIVE['functions'], speech_polylogInitiator=['alias'])),
                              'declares no parameter')):
            tree, _ = self.assert_left([include('dialogInitiator')], DIALOG, text, native=native)
            self.assertEqual([v['name'] for v in tree['variables']], ['t_dialogParameters', 't_dialogParticipants'])
        # The instant variant does not write movePlayer, so its absence does not block it.
        self.assertEqual(len(run([include('dialogInitiator_instant')], DIALOG, native=without('dialog_fields', 'movePlayer'))[1]['sites']), 1)

    def test_another_include_and_a_skipped_tree_are_left_alone(self):
        tree, report = run([include('dialogInitiator_other'), include('dialogInitiator', 'final/other.xml')], DIALOG)
        self.assertEqual((report['sites'], report['left']), ([], []))
        self.assertFalse(any('blocked' in n for n in self.walk(tree['root'])))
        tree, report = run([include('dialogInitiator')], DIALOG, skip={'main'})
        self.assertEqual((report['sites'], report['left'], at(tree, 'Root/1/0')['op']), ([], [], 'IncludeTree'))


FIGHT = ['$t_fightOptions.opponent = $t_customBehaviorParams.entity',
         '$t_fightOptions.combatRegimeOverride = $enum:combatTreeExecutionRegime.keepRunning',
         '$t_fightOptions.listener = $this.id', '$t_fightOptions.preferredWeaponKind = $enum:weaponChange.unarmed']
WAIT = node('Wait', duration='-1')


def fight(statements=FIGHT, rest=(WAIT,), before=()):
    return [node('Sequence', [*before, expression(*statements), include('fight', 'final/sb_combat_fight.xml'), *copy.deepcopy(list(rest))])]


class FightTests(unittest.TestCase):
    def assert_left(self, behavior, text, variables=(OPTIONS,), **kwargs):
        tree, report = run(behavior, variables, **kwargs)
        self.assertEqual((len(report['sites']), len(report['left'])), (0, 1), text)
        self.assertIn(text, report['left'][0]['reason'])
        self.assertEqual(at(tree, report['left'][0]['path'])['blocked'], [library.REASON + report['left'][0]['reason']])

    def test_the_fight_becomes_the_native_template_under_the_unarmed_context(self):
        tree, report = run(fight(before=[node('Success')]), [OPTIONS])
        site, = report['sites']
        sequence = at(tree, 'Root/1/0')
        self.assertEqual([c['op'] for c in sequence['children']], ['Success', 'EntityContextElement'])
        context = sequence['children'][1]
        self.assertEqual((context['attributes'], context['stand_in'], context['source_op']),
                         (dict(context=q('combat_forceUnarmed')), 'Function_combat_fightRepeated_template', 'IncludeTree'))
        held, = context['children']
        self.assertEqual([(c['op'], c['attributes']) for c in held['children']],
                         [('Function_combat_fightRepeated_template', dict(target=q('$t_customBehaviorParams.entity'))),
                          ('Wait', dict(duration=q('-1')))])
        self.assertEqual((site['path'], site['decision'], site['held'], site['unarmed']),
                         ('Root/1/0/1', 15, ['Wait'], dict(context='combat_forceUnarmed', proven_offline=False)))
        self.assertEqual([n['path'] for n in site['nodes']], ['Root/1/0/1', 'Root/1/0/1/0', 'Root/1/0/1/0/0'])
        self.assertEqual({f['field']: f['handling'] for f in site['fields']},
                         dict(opponent='parameter', combatRegimeOverride='dropped', listener='dropped', preferredWeaponKind='approximated'))
        # The consumed Expression is gone: nothing writes t_fightOptions any more.
        self.assertFalse(any('t_fightOptions' in v for n, _, _ in library._walk(tree['root']) for v in n['attributes'].values()))

    def test_any_other_shape_or_option_is_left_blocked(self):
        self.assert_left(fight(rest=()), 'nothing follows fight')
        self.assert_left(fight([FIGHT[0], FIGHT[1], FIGHT[2], '$t_fightOptions.preferredWeaponKind = $enum:weaponChange.primary']),
                         'only $enum:weaponChange.unarmed has a stand-in')
        self.assert_left(fight(FIGHT[:3]), 'preferredWeaponKind is not set')
        self.assert_left(fight([FIGHT[0], FIGHT[2], FIGHT[3]]), 'combatRegimeOverride is not set')
        self.assert_left(fight(FIGHT + ['$t_fightOptions.standStill = true']), 'standStill has no declared handling')
        self.assert_left(fight(['$t_fightOptions.opponent = $__null + 1'] + FIGHT[1:]), 'opponent is not a variable')
        self.assert_left(fight(FIGHT[:2] + ['$t_fightOptions.listener = $boss', FIGHT[3]]), 'listener is another entity')
        self.assert_left(fight(FIGHT + ['$count = 1']), 'beside other statements')
        self.assert_left(fight(before=[expression('$t_fightOptions.standStill = true')]), 'assigned elsewhere')
        self.assert_left([node('Sequence', [node('Success'), include('fight', 'final/sb_combat_fight.xml'), WAIT])], 'not preceded')
        self.assert_left([node('Loop', [include('fight', 'final/sb_combat_fight.xml')])], 'not a step of a sequence')
        self.assert_left(fight(), 'does not declare t_fightOptions', variables=())
        self.assert_left(fight(), 'native entity context is not in retail KCD2', native=without('entity_contexts', 'combat_forceUnarmed'))
        self.assert_left(fight(), 'native function is not in retail KCD2', native=without('functions', 'combat_fightRepeated_template'))


LEADER = expression('$t_distanceMove_params.movementTargetType = $enum:movementTargetType.wuid',
                    '$t_distanceMove_params.speed = $enum:movementSpeed.run', '$t_followFormationParams.formation.leader = $this.id',
                    "$t_followFormationParams.leaderCallback.file = 'final/moveUtils.xml'",
                    "$t_followFormationParams.leaderCallback.tree = 'distanceMove'")
TARGET = node('LinkDataFilter', Child='t_distanceMove_params.target')
FOLLOW = node('LinkDataFilter', Child='t_followFormationParams.formation.leader')
FORM = include('followNPC_inFormation', 'final/questUtils.xml')


class FormationTests(unittest.TestCase):
    def assert_left(self, text, behavior=(FORM,), variables=(FORMATION, MOVE), init=(), **kwargs):
        tree, report = run(copy.deepcopy(list(behavior)), variables, copy.deepcopy(list(init)), **kwargs)
        self.assertEqual((len(report['sites']), len(report['left'])), (0, 1), text)
        self.assertIn(text, report['left'][0]['reason'])
        self.assertEqual(at(tree, report['left'][0]['path'])['blocked'], [library.REASON + report['left'][0]['reason']])

    def call(self, tree, path='Root/1/0'):
        stand_in = at(tree, path)
        self.assertEqual((stand_in['op'], stand_in['stand_in'], stand_in['children'][0]['attributes']),
                         ('Sequence', 'Function_moveInFormation_inFormation',
                          dict(expressions=q("$t_followFormationParams.formation.type = 'followNPC'"))))
        self.assertEqual(stand_in['children'][1]['op'], 'Function_moveInFormation_inFormation')
        return {k: v[1:-1] for k, v in stand_in['children'][1]['attributes'].items()}

    def test_a_follower_tree_passes_no_destination_as_retail_does(self):
        tree, report = run([copy.deepcopy(FORM)], [FORMATION], init=[copy.deepcopy(FOLLOW)])
        self.assertEqual(self.call(tree), dict(destination='$__null', followEnabled='false',
                                               followFormationParams='$t_followFormationParams', pathOffset='0.000000',
                                               successDistance='0.000000'))
        site, = report['sites']
        self.assertEqual((site['decision'], site['role'], site['formation']),
                         (16, 'no callback', dict(name='followNPC', kcd1_spots=SPOTS, kcd2_spots=SPOTS, spots_equal=True)))
        self.assertEqual([(f['field'], f['handling'], f['assigned'][0]['value']) for f in site['fields']],
                         [('formation.leader', 'passed', '<search result>')])

    def test_a_leader_tree_moves_to_the_target_of_its_distance_move(self):
        move = node('ExactMove', destinationSpecification='t_distanceMove_params.target', directionSpecification='t_distanceMove_params.target')
        tree, report = run([node('Sequence', [copy.deepcopy(FORM), move])], [FORMATION, MOVE], init=[copy.deepcopy(TARGET), copy.deepcopy(LEADER)])
        self.assertEqual(self.call(tree, 'Root/1/0/0')['destination'], '$t_distanceMove_params.target')
        site, = report['sites']
        self.assertEqual(site['role'], 'leader callback named')
        self.assertEqual({f['field']: f['handling'] for f in site['fields']},
                         {'formation.leader': 'passed', 'leaderCallback (distanceMove)': 'approximated',
                          't_distanceMove_params.speed': 'dropped'})
        self.assertEqual(field(site, 't_distanceMove_params.speed')['assigned'], [dict(value='$enum:movementSpeed.run')])
        self.assertIn('distanceMove', site['behaviours_dropped'][0])

    def test_formation_offsets_that_differ_are_recorded(self):
        other = [['left', '-1.0', '2.0', '0.5']]
        _, report = run([copy.deepcopy(FORM)], [FORMATION], formations={'followNPC': other})
        self.assertEqual(report['sites'][0]['formation'], dict(name='followNPC', kcd1_spots=other, kcd2_spots=SPOTS, spots_equal=False))

    def test_an_unknown_parameter_blocks_and_never_defaults(self):
        def leader(*changes, drop=()):
            statements = [s for s in literal_statements(LEADER) if not any(d in s for d in drop)] + list(changes)
            return [copy.deepcopy(TARGET), expression(*statements)]
        self.assert_left('formation.type has no declared handling', init=[expression("$t_followFormationParams.formation.type = 'pairs'")])
        self.assert_left('formation.speedLimit has no declared', init=[expression('$t_followFormationParams.formation.speedLimit = $enum:movementSpeed.run')])
        self.assert_left('leaderCallback.host has no declared', init=[expression('$t_followFormationParams.leaderCallback.host = $__object.id')])
        self.assert_left('not distanceMove', init=leader(drop=['leaderCallback.tree']))
        self.assert_left('not distanceMove', init=leader("$t_followFormationParams.leaderCallback.tree = 'walkInGroup'", drop=['leaderCallback.tree']))
        self.assert_left('not distanceMove', behavior=[node('Sequence', [copy.deepcopy(LEADER), copy.deepcopy(FORM)])], init=[copy.deepcopy(TARGET)])
        self.assert_left('not given an entity target', init=leader(drop=['movementTargetType']))
        self.assert_left('not given an entity target', init=[copy.deepcopy(LEADER)])
        self.assert_left('autospeed has no declared handling', init=leader('$t_distanceMove_params.autospeed = true'))
        self.assert_left('does not declare t_distanceMove_params', variables=[FORMATION], init=leader())
        self.assert_left('does not declare t_followFormationParams', variables=[MOVE])
        self.assert_left('used outside an assignment', behavior=[node('Sequence', [node('SetVariable', variable='t_followFormationParams'), copy.deepcopy(FORM)])])
        self.assert_left('native formation is not in retail KCD2', native=without('formations', 'followNPC'))
        self.assert_left('KCD1 formation is not in the source definitions', formations={})
        self.assert_left('native function is not in retail KCD2', native=without('functions', 'moveInFormation_inFormation'))


def literal_statements(expression_node):
    return [s.strip().rstrip(',') for s in expression_node['attributes']['expressions'][1:-1].split('\n')]


class ContractTests(unittest.TestCase):
    """Layer 1 compares an emitted tree with the nodes its sites declare."""

    def emitted(self, report):
        root = E.Element('Root')
        E.SubElement(root, 'OnInit')
        sequence = E.SubElement(E.SubElement(root, 'Behavior'), 'Sequence')
        for declared in report['sites'][0]['nodes'][1:]:
            E.SubElement(sequence, declared['op'], declared['attributes'])
        return root

    def test_a_site_whose_emitted_nodes_differ_from_its_declaration_is_a_problem(self):
        _, report = run([include('dialogInitiator')], DIALOG)
        self.assertEqual(library.check(report, dict(main=self.emitted(report))), {})
        self.assertEqual(library.check(report, {}), {})  # a tree that is not emitted is not compared
        mutations = dict(
            another_function=lambda root: setattr(root[1][0][1], 'tag', 'Function_speech_dialogInitiator'),
            another_preset=lambda root: root[1][0][1].set('preset', '$enum:dialogPreset.ingame'),
            a_dropped_parameter=lambda root: root[1][0][1].attrib.pop('participants'),
            an_added_parameter=lambda root: root[1][0][1].set('recipient', '$__player'),
            another_copy=lambda root: root[1][0][0].set('expressions', '$t_polylogParameters.enableGreeting = true'),
            a_missing_call=lambda root: root[1][0].remove(root[1][0][1]),
            a_missing_stand_in=lambda root: root[1].remove(root[1][0]),
            another_wrapper=lambda root: setattr(root[1][0], 'tag', 'Selector'))
        for name, mutate in mutations.items():
            root = self.emitted(report)
            mutate(root)
            self.assertTrue(library.check(report, dict(main=root)).get('main'), name)

    def test_finish_reads_the_nodes_where_a_later_pass_left_them(self):
        source = model([node('Sequence', [include('dialogInitiator')])], DIALOG)
        report = library.apply(source, NATIVE, {})
        body = source['behavior_documents'][OWN]['trees']['main']
        sequence = at(body, 'Root/1/0')
        sequence['children'].insert(0, node('Success'))
        sequence['children'][1]['children'][1]['attributes']['alias'] = q('$renamed')
        report = library.finish(report)
        self.assertEqual((report['sites'][0]['path'], report['stand_ins'][0]['path']), ('Root/1/0/1', 'Root/1/0/1'))
        self.assertEqual(report['sites'][0]['nodes'][2]['attributes']['alias'], '$renamed')
        self.assertNotIn('_refs', report)
        gone = library.apply(model([node('Sequence', [include('dialogInitiator')])], DIALOG), NATIVE, {})
        gone['_refs'][0][1]['root']['children'][1]['children'] = []
        with self.assertRaises(ValueError): library.finish(gone)

    def test_the_stand_ins_are_declared_with_their_approval_and_registered_with_the_compiler(self):
        declared = library.rules()
        self.assertEqual({(key, row['decision'], row['target']) for key, row in declared.items()}, {
            ('IncludeTree final/dialogutils.xml:dialogInitiator', 14, 'Function_speech_polylogInitiator'),
            ('IncludeTree final/dialogutils.xml:dialogInitiator_instant', 14, 'Function_speech_polylogInitiator'),
            ('IncludeTree final/sb_combat_fight.xml:fight', 15, 'Function_combat_fightRepeated_template'),
            ('IncludeTree final/questutils.xml:followNPC_inFormation', 16, 'Function_moveInFormation_inFormation')})
        self.assertTrue(all('2026-11-17' in row['approved'] and row['rule'] for row in declared.values()))
        self.assertEqual({c['decision'] for c in library.IN_GAME_CHECKS}, {14, 15, 16})
        import campaign_ai_types
        import campaign_behavior
        contracts.register()
        for op, fields in library.CONTRACTS.items():
            self.assertEqual(campaign_behavior.CONTRACTS[op], fields)
        self.assertEqual(campaign_ai_types.ENGINE_TYPE_ADAPTERS[library.NATIVE_PARAMETERS], 'dialog:parameters:initiator')

    def test_only_a_function_retail_defines_is_added_to_the_catalog(self):
        catalog = dict(nodes={'Function_speech_polylogInitiator': dict(attributes=['alias'], children=[])})
        library.supplement(catalog, without('functions', 'moveInFormation_inFormation'))
        self.assertEqual(catalog['nodes']['Function_speech_polylogInitiator'], dict(attributes=['alias'], children=[]))
        self.assertEqual(catalog['nodes']['Function_combat_fightRepeated_template']['attributes'], ['target'])
        self.assertNotIn('Function_moveInFormation_inFormation', catalog['nodes'])

    def test_native_evidence_is_read_from_the_archive(self):
        import io
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, 'w') as archive:
            archive.writestr('AI/speech/polyloginitiator.xml', '<BehaviorTrees><BehaviorTree name="speech_polylogInitiator" is_function="1">'
                             '<Parameters><Variable name="alias"/><Variable name="preset"/></Parameters><Root>'
                             '<IfCondition condition="$preset == $enum:dialogPreset.ignored"/>'
                             '<Expression expressions="$dialogParameters.alias = $alias"/></Root></BehaviorTree>'
                             '<BehaviorTree name="combat_fightRepeated_template" is_function="0"><Parameters><Variable name="target"/>'
                             '</Parameters></BehaviorTree></BehaviorTrees>')
            archive.writestr('AI/quests/a.xml', '<BehaviorTrees><BehaviorTree name="x"><Root>'
                             '<EntityContextElement context="combat_forceUnarmed"><Success/></EntityContextElement>'
                             '<Expression expressions="$dialogParameters.notASpeechFile = 1"/></Root></BehaviorTree></BehaviorTrees>')
            archive.writestr('AI/FormationDefinitions.xml', '<FormationDefinitions><Formation name="followNPC">'
                             '<Spot name="left" radius="0.5" x="-0.7" y="1.7"/></Formation></FormationDefinitions>')
            archive.writestr('Quests/b.xml', '<x>$enum:dialogPreset.notAI</x>')
        with zipfile.ZipFile(blob) as archive:
            self.assertEqual(library.native_evidence(archive), dict(
                functions={'speech_polylogInitiator': ['alias', 'preset']}, literals=['$enum:dialogPreset.ignored'],
                dialog_fields=['alias'], entity_contexts=['combat_forceUnarmed'],
                formations={'followNPC': [['left', '-0.7', '1.7', '0.5']]}))


@unittest.skipUnless(RETAIL, 'requires installed retail KCD1 and KCD2 scripts')
class RetailTests(unittest.TestCase):
    def test_retail_kcd2_has_every_name_the_stand_ins_write(self):
        with zipfile.ZipFile(KCD2 / 'Data/Scripts.pak') as archive:
            native = library.native_evidence(archive)
        for function, op in library.FUNCTIONS.items():
            self.assertEqual(set(library.CONTRACTS[op]) - set(native['functions'][function]), set(), function)
        self.assertEqual(set(native['functions']['speech_polylogInitiator']), set(library.CONTRACTS['Function_speech_polylogInitiator']))
        self.assertEqual(native['functions']['combat_fightRepeated_template'], ['target'])
        self.assertLessEqual({'$enum:dialogPreset.ignored', *library.APPROACH.values()}, set(native['literals']))
        self.assertLessEqual({target for target, _ in (*library.COPIED.values(), *library.POSITIONING.values())} | {'alias'},
                             set(native['dialog_fields']))
        self.assertIn(library.UNARMED, native['entity_contexts'])
        self.assertIn(library.FORMATION_NAME, native['formations'])

    def test_the_kcd1_defaults_and_formation_are_the_ones_retail_kcd1_declares(self):
        import tempfile
        from campaign_ai_types import AITypeSource
        from campaign_sources import RetailSourceReader, retail_sources
        with tempfile.TemporaryDirectory() as tmp:
            types = AITypeSource.load(KCD1, retail_sources, 'C2', Path(tmp) / 'types')
            declared = {m.get('name'): (m.text or '').strip() for key in ('dialog:parameters', 'dialog:parameters:initiator')
                        for m in types.types[key][1] if m.tag.lower() == 'member'}
        self.assertEqual(declared, library.DIALOG_DEFAULTS)
        with RetailSourceReader(KCD1) as reader, zipfile.ZipFile(KCD2 / 'Data/Scripts.pak') as archive:
            source = library.formation_spots(reader(KCD1, dict(f=('Scripts.pak', 'Libs/AI/FormationDefinitions.xml')))['f']['data'])
            self.assertEqual(source[library.FORMATION_NAME], library.native_evidence(archive)['formations'][library.FORMATION_NAME])


if __name__ == '__main__': unittest.main()
