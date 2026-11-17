"""Converter C2: combat requests as interrupts, fights of the combat converter, opponents."""
import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_controller_combat as combat
import campaign_controller_contracts as contracts
import quest_controller_conversion as c2

DOCUMENT = 'libs/ai/quests/q_example.xml'
MESSAGE = 'combat:stimulus:customBehaviorRequest'


def node(op, children=(), **attributes):
    return dict(op=op, attributes=attributes, children=list(children), text='')


def q(value):
    return '"%s"' % value


def send(values, target="t_actors['guard']", op='InstantSendMessageToNPC'):
    return node(op, **{'targets' if 'Multi' in op else 'target': target}, type=MESSAGE, values=values)


def model(trees, registered=None, variables=None):
    points = [dict(file='quests/q_example.xml', tree=tree, kind='behavior_callback', name=name)
              for name, tree in (registered or {name: name for name in trees}).items()]
    return dict(quest='q_example', controller_registration=dict(entry_points=points),
                behavior_documents={DOCUMENT: dict(trees={
                    name: dict(variables=list((variables or {}).get(name, ())), root=node('Root', [copy.deepcopy(root)]))
                    for name, root in trees.items()})})


def body(subject, tree):
    return subject['behavior_documents'][DOCUMENT]['trees'][tree]['root']['children'][0]


READS = node('Sequence', [node('AddLink', From=q('this.id'), To=q('t_customBehaviorParams.entity')),
                          node('Expression', expressions=q('$enemy = $t_customBehaviorParams.entity'))])
FIGHT = dict(tag='duel', objective='angry', actor='smith', partners=['a', 'b'], document=DOCUMENT, tree='duel',
             outcomes=dict(won=dict(cutscene='after', schedule_tag='sit')))


class RequestTests(unittest.TestCase):
    def test_a_request_becomes_an_interrupt_with_the_decided_policy(self):
        subject = model(dict(entry=send('behaviorSource($this.id),behaviorName(brawl),entity($__player)'), brawl=READS))
        report = combat.apply(subject)
        site = body(subject, 'entry')
        self.assertEqual((site['op'], site['source_op'], site['stand_in'], site['requires']),
                         ('AddInterrupt_wuidData', 'InstantSendMessageToNPC', 'interrupt policy', [(DOCUMENT, 'brawl')]))
        self.assertEqual(site['attributes'], dict(
            data=q('$__player'), Target=q("t_actors['guard']"), Host=q('$this.id'), Behavior=q('brawl'), Priority=q('161'),
            IgnorePriorityOnPreviousInterrupt=q('false'), urgency=q('Fast'), Aliveness=q('Alive'), Privileged=q('false'),
            FastForward=q('false')))
        self.assertEqual(report['registrations'], [dict(behavior='brawl', document=DOCUMENT, tree='brawl',
                                                        signature='wuidData', initial_state='Enabled')])
        self.assertEqual((report['policy']['priority'], report['policy']['urgency']), (161, 'Fast'))
        self.assertIn('decision 12a', report['policy']['approved'])
        self.assertEqual(report['stand_ins'], [dict(tree='entry', path='Root/0', source='customBehaviorRequest',
                                                    target='AddInterrupt_wuidData')])
        # The behaviour reads its parameter where it read the stored request.
        fight = subject['behavior_documents'][DOCUMENT]['trees']['brawl']
        self.assertEqual(([n['attributes'] for n in body(subject, 'brawl')['children']], fight['parameters']),
                         ([dict(From=q('this.id'), To=q('data')), dict(expressions=q('$enemy = $data'))],
                          [dict(name='data', type='_wuid', values='', isPersistent='0', form='single', requirementType='In')]))

    def test_a_behaviour_that_never_reads_the_entity_takes_the_empty_signature(self):
        subject = model(dict(entry=node('Sequence', [send("behaviorSource($__object.id),behaviorName('brawl'),entity($this.id)", 'this.id'),
                                                     send("behaviorSource($this.id),behaviorName('brawl')")]),
                             brawl=node('Success')))
        report = combat.apply(subject)
        first, second = body(subject, 'entry')['children']
        self.assertEqual((first['op'], first['attributes']['Target'], first['attributes']['Host'], 'data' in first['attributes']),
                         ('AddInterrupt_empty', q('this.id'), q('$__object.id'), False))
        self.assertEqual([(r['signature'], r['entity_not_passed']) for r in report['interrupts']],
                         [('empty', True), ('empty', False)])
        self.assertNotIn('parameters', subject['behavior_documents'][DOCUMENT]['trees']['brawl'])
        self.assertEqual(len(report['registrations']), 1)

    def test_the_registration_tag_names_the_behaviour_and_its_tree_is_required(self):
        subject = model(dict(entry=send('behaviorSource($this.id),behaviorName(public)'), hidden=node('Success')),
                        registered=dict(public='hidden'))
        report = combat.apply(subject)
        self.assertEqual((body(subject, 'entry')['attributes']['Behavior'], body(subject, 'entry')['requires']),
                         (q('public'), [(DOCUMENT, 'hidden')]))
        self.assertEqual([(r['behavior'], r['tree']) for r in report['registrations']], [('public', 'hidden')])

    def test_a_request_without_a_native_form_is_left_with_its_reason(self):
        ok = 'behaviorSource($this.id),behaviorName(brawl)'
        cases = [(send(ok + ',suppressStimuli(false)'), node('Success'), 'fields outside behaviorSource, behaviorName, entity'),
                 (send('behaviorSource($this.id),behaviorName($name)'), node('Success'), 'behaviour name is not static'),
                 (send('behaviorSource($area),behaviorName(brawl)'), node('Success'), 'behaviour source is not the controller'),
                 (send('behaviorSource($this.id),behaviorName(missing)'), node('Success'),
                  'Missing or ambiguous behavior callback registration: missing'),
                 (send(ok + ',entity(a(b))'), node('Success'), 'request fields cannot be read'),
                 (send(ok), READS, 'behaviour reads an opponent a request does not pass'),
                 (send(ok + ',entity($x)'), node('Expression', expressions=q('$n = $t_customBehaviorParams.behaviorName')),
                  'behaviour reads the stored request beyond its entity: behaviorName'),
                 (send(ok + ',entity($x)'), node('ExecuteLua', code=q('Dump(data.t_customBehaviorParams.entity)')),
                  'behaviour reads the stored request beyond its entity: <script>'),
                 (send(ok + ',entity($x)'), node('VarOperation', varName=q('t_customBehaviorParams')),
                  'behaviour reads the stored request beyond its entity: <whole>')]
        for request, fight, reason in cases:
            subject = model(dict(entry=request, brawl=fight))
            report = combat.apply(subject)
            self.assertEqual((body(subject, 'entry')['op'], [r['reason'] for r in report['left']], report['interrupts'],
                              report['registrations']), ('InstantSendMessageToNPC', [reason], [], []), reason)
            self.assertEqual(body(subject, 'brawl'), fight)
        subject = model(dict(entry=send(ok + ',entity($x)'), brawl=READS), variables=dict(brawl=[dict(name='data', type='_int')]))
        self.assertEqual(combat.apply(subject)['left'][0]['reason'], 'behaviour has a variable named data')
        # Another message is not a request at all.
        other = node('InstantSendMessageToNPC', target='this.id', type='cryofreeze:request', values='freeze(true)')
        subject = model(dict(entry=other))
        self.assertEqual((combat.apply(subject)['left'], body(subject, 'entry')['op']), ([], 'InstantSendMessageToNPC'))

    def test_a_request_to_several_targets_is_blocked_not_sent_as_a_message(self):
        subject = model(dict(entry=send('behaviorSource($this.id),behaviorName(brawl)', 'boys', 'InstantMultiSendMessageToNPC'),
                             brawl=node('Success')))
        report = combat.apply(subject)
        self.assertEqual((body(subject, 'entry')['op'], body(subject, 'entry')['blocked'], report['left'][0]['reason']),
                         ('InstantMultiSendMessageToNPC', [combat.MANY], 'several targets'))

    def test_sub_brain_state_in_an_interrupt_behaviour_is_blocked_by_name(self):
        fight = node('Sequence', [node('VarOperation', varName=q('t_fightParams'), operation=q('Reinit')),
                                  node('Expression', expressions=q('$t_fightParams.opponent = $__player, $t_state = $enum:combatState.fight')),
                                  node('Expression', expressions=q('$t_stateful = 1')),
                                  node('Expression', expressions=q('$t_exitCombatSubbrain = true,'))])
        subject = model(dict(entry=send('behaviorSource($this.id),behaviorName(brawl)'), brawl=fight, other=fight))
        report = combat.apply(subject)
        self.assertEqual([n.get('blocked') for n in body(subject, 'brawl')['children']],
                         [[combat.STATE + 't_fightParams'], [combat.STATE + 't_fightParams, t_state'], None,
                          [combat.STATE + 't_exitCombatSubbrain']])
        self.assertEqual([(r['tree'], r['path'], r['variables']) for r in report['subbrain_state']],
                         [('brawl', 'Root/0/0', ['t_fightParams']), ('brawl', 'Root/0/1', ['t_fightParams', 't_state']),
                          ('brawl', 'Root/0/3', ['t_exitCombatSubbrain'])])
        # A tree no request names is not an interrupt behaviour.
        self.assertEqual([n.get('blocked') for n in body(subject, 'other')['children']], [None] * 4)


class HandedTests(unittest.TestCase):
    def trees(self):
        return dict(entry=node('Sequence', [send('behaviorSource($this.id),behaviorName(duel),entity($__player)', "t_actors['smith']"),
                                            send("behaviorSource($this.id),behaviorName(help),entity($t_actors['smith'])", 'friends',
                                                 'InstantMultiSendMessageToNPC'),
                                            send('behaviorSource($this.id),behaviorName(brawl),entity($__player)')]),
                    duel=node('Sequence', [node('AddOpponent', who=q('t_customBehaviorParams.entity')),
                                           send('behaviorSource($__object.id),behaviorName(brawl)', 'this.id'), node('Success')]),
                    help=node('Sequence', [node('AddOpponent', who=q('t_customBehaviorParams.entity')), node('Success')]),
                    brawl=node('Success'))

    def test_a_fight_of_the_combat_converter_is_handed_with_its_partners_half(self):
        subject = model(self.trees())
        before = copy.deepcopy([body(subject, name) for name in ('duel', 'help')])
        report = combat.apply(subject, [FIGHT])
        steps = body(subject, 'entry')['children']
        self.assertEqual([(s['op'], s.get('source_op'), s.get('handed')) for s in steps],
                         [('Success', 'InstantSendMessageToNPC', 'campaign_combat'),
                          ('Success', 'InstantMultiSendMessageToNPC', 'campaign_combat'),
                          ('AddInterrupt_empty', 'InstantSendMessageToNPC', None)])
        self.assertEqual((steps[0]['attributes'], 'blocked' in steps[1]), ({}, False))
        handed = report['handed'][0]
        self.assertEqual((handed['trees'], [(s['behavior'], s['role'], s['path']) for s in handed['sites']], handed['converter']),
                         (['duel', 'help'], [('duel', 'actor', 'Root/0/0'), ('help', 'partners', 'Root/0/1')], 'campaign_combat'))
        # The handed trees are left exactly as written: no opponent stand-in, no parameter.
        self.assertEqual(([body(subject, name) for name in ('duel', 'help')], report['opponents'], report['left']),
                         (before, [], []))
        self.assertEqual([r['behavior'] for r in report['registrations']], ['brawl'])

    def test_without_the_combat_converter_nothing_is_handed(self):
        subject = model(self.trees())
        report = combat.apply(subject)
        self.assertEqual((report['handed'], [s['op'] for s in body(subject, 'entry')['children']]),
                         ([], ['AddInterrupt_wuidData', 'InstantMultiSendMessageToNPC', 'AddInterrupt_empty']))
        # A request against another actor is not the partners' half.
        other = dict(FIGHT, actor='miller')
        subject = model(self.trees())
        self.assertEqual(combat.apply(subject, [other])['handed'][0]['trees'], ['duel'])

    def test_the_ledger_keeps_a_handed_tree_out_of_the_residue_and_refuses_it_emitted(self):
        tree = E.Element('BehaviorTree', name='duel'); E.SubElement(tree, 'Variables'); E.SubElement(tree, 'Root')
        source = dict(quest='q_example', behavior_documents={DOCUMENT: dict(trees=dict(duel=dict(variables=[], root=node('Root'))))})
        def run(unresolved):
            record = dict(document=DOCUMENT, tree='duel', unresolved=unresolved, native_emitted=not unresolved)
            return c2.ledger(dict(model=source, prepared=dict(scope_resolutions=[], renamed=[], rename_blocked=[]),
                                  behaviors={} if unresolved else {'AI/x.xml': E.tostring(tree)},
                                  conversion=dict(trees=[record]), combat=dict(handed=[dict(trees=['duel'])])))
        led = run([dict(reason='Inexpressible as one native operation: AddOpponent')] * 2)
        self.assertEqual((led['trees'], led['blockers'], led['tree_status']),
                         (dict(total=1, handed=1), [], [dict(tree='duel', status='handed', blocked_sites=2, reasons=1)]))
        self.assertEqual(led['layers']['source_equivalence']['verdict'], 'PASS')
        self.assertEqual(run([])['layers']['source_equivalence']['failures'],
                         [dict(tree='duel', problems=['a tree handed to the combat converter was emitted'])])


class OpponentTests(unittest.TestCase):
    def apply(self, root):
        subject = model(dict(entry=root))
        return body(subject, 'entry'), combat.apply(subject)

    def test_an_opponent_added_in_a_loop_is_the_flagged_target_stand_in(self):
        for loop in ('For', 'While', 'Loop'):
            root, report = self.apply(node(loop, [node('Sequence', [node('AddOpponent', who=q('opponent'), IgnoreFail=q('true')),
                                                                    node('Success')])]))
            site = root['children'][0]['children'][0]
            self.assertEqual((site['op'], site['source_op'], site['stand_in'], site['attributes']),
                             ('SuppressFailure', 'AddOpponent', 'InstantSetTarget', {}))
            self.assertEqual((site['children'][0]['op'], site['children'][0]['attributes'], len(root['children'][0]['children'])),
                             ('InstantSetTarget', dict(Target=q('opponent')), 2))
            self.assertEqual([(r['target'], r['who'], r['path']) for r in report['opponents']],
                             [('InstantSetTarget', 'opponent', 'Root/0/0/0')])
            self.assertIn('pending the in-game check', report['opponents'][0]['approved'])
            self.assertEqual(report['stand_ins'], [dict(tree='entry', path='Root/0/0/0', source='AddOpponent', target='InstantSetTarget')])
        root, _ = self.apply(node('Loop', [node('AddOpponent', who=q('x'), IgnoreFail=q('false'))]))
        self.assertEqual((root['children'][0]['op'], root['children'][0]['attributes']), ('InstantSetTarget', dict(Target=q('x'))))

    def test_an_opponent_in_a_sequence_holds_the_skirmish_beside_the_rest(self):
        first, last = node('Wait', duration=q('1s')), node('Wait', duration=q('2s'))
        root, report = self.apply(node('Sequence', [first, node('AddOpponent', who=q('__player'), IgnoreFail=q('true')),
                                                    node('Success'), last]))
        self.assertEqual(([c['op'] for c in root['children']], root['children'][0]), (['Wait', 'Parallel'], first))
        parallel = root['children'][1]
        self.assertEqual((parallel['attributes'], parallel['source_op'], parallel['stand_in']),
                         (dict(successMode=q('Any'), failureMode=q('Any')), 'AddOpponent', 'AddToSkirmish'))
        self.assertEqual([(c['op'], c['attributes']) for c in parallel['children']],
                         [('AddToSkirmish', dict(TargetNPC=q('__player'), RelationOverride=q('Hostile'))), ('Sequence', {})])
        self.assertEqual(parallel['children'][1]['children'], [node('Success'), last])
        self.assertEqual([(r['target'], r['path'], r['ignore_fail_dropped']) for r in report['opponents']],
                         [('AddToSkirmish', 'Root/0/1', True)])
        self.assertIn('stand-in 1', report['opponents'][0]['approved'])

    def test_two_opponents_in_one_sequence_nest(self):
        root, report = self.apply(node('Sequence', [node('AddOpponent', who=q('a')), node('AddOpponent', who=q('b')), node('Success')]))
        inner = root['children'][0]['children'][1]['children'][0]
        self.assertEqual((inner['op'], inner['children'][0]['attributes']['TargetNPC'], [r['path'] for r in report['opponents']]),
                         ('Parallel', q('b'), ['Root/0/0', 'Root/0/0/1/0']))

    def test_an_opponent_without_an_approved_shape_is_left(self):
        cases = [(node('Sequence', [node('Success'), node('AddOpponent', who=q('x'))]), 'not followed by the rest of a sequence'),
                 (node('Selector', [node('AddOpponent', who=q('x')), node('Success')]), 'not followed by the rest of a sequence'),
                 (node('OnInit', [node('Sequence', [node('AddOpponent', who=q('x')), node('Success')])]),
                  'in OnInit: the behaviour body would have to move under the skirmish'),
                 (node('Loop', [node('AddOpponent', who=q('x'), Extra=q('1'))]), 'fields outside who and IgnoreFail'),
                 (node('Loop', [node('AddOpponent', who=q('x'), IgnoreFail=q('$flag'))]), 'fields outside who and IgnoreFail'),
                 (node('Loop', [node('AddOpponent', who=q(''))]), 'fields outside who and IgnoreFail')]
        for root, reason in cases:
            before = repr(root)
            after, report = self.apply(root)
            self.assertEqual((repr(after), [(r['operation'], r['reason']) for r in report['left']], report['opponents']),
                             (before, [('AddOpponent', reason)], []), reason)


class LoweringTests(unittest.TestCase):
    """The rewritten nodes through the production compiler's node lowering."""

    def lower(self, source):
        import campaign_behavior
        from campaign_dependencies import DependencyImporter
        contracts.register()
        catalog = dict(nodes={op: dict(attributes=list(fields), children=[])
                              for op, fields in campaign_behavior.CONTRACTS.items()}, variable_types=[], enum_types=[])
        compiler = campaign_behavior.BehaviorCompiler([], 'C2', catalog, importer=DependencyImporter({}, {}))
        compiler.variables = {'t_actors': dict(name='t_actors', type='common:wuid', form='associative')}
        record = dict(unresolved=[], buff_dependencies=[], item_dependencies=[], includes=[])
        emitted = compiler.lower_node(source, 'q_example', DOCUMENT, 'entry', 'Root/0', record)
        return emitted, record

    def test_the_nodes_are_emitted_in_the_retail_form(self):
        subject = model(dict(entry=node('Sequence', [send('behaviorSource($this.id),behaviorName(brawl),entity($__player)'),
                                                     node('AddOpponent', who=q('__player')), node('Success')]), brawl=READS))
        combat.apply(subject)
        emitted, record = self.lower(body(subject, 'entry'))
        self.assertEqual(record['unresolved'], [])
        self.assertEqual(record['includes'], [('q_example', DOCUMENT, 'brawl')])
        self.assertEqual(E.tostring(emitted, encoding='unicode'),
                         '<Sequence><AddInterrupt_wuidData data="$__player" Target="$t_actors[\'guard\']" Host="$this.id" '
                         'Behavior="\'brawl\'" Priority="161" IgnorePriorityOnPreviousInterrupt="false" urgency="Fast" '
                         'Aliveness="Alive" Privileged="false" FastForward="false" />'
                         '<Parallel successMode="Any" failureMode="Any"><AddToSkirmish TargetNPC="$__player" RelationOverride="Hostile" />'
                         '<Sequence><Success /></Sequence></Parallel></Sequence>')
        target, _ = self.lower(node('InstantSetTarget', Target=q('hitReaction.attacker')))
        self.assertEqual(E.tostring(target, encoding='unicode'), '<InstantSetTarget Target="$hitReaction.attacker" />')

    def test_a_blocked_node_is_reported_and_still_lowered(self):
        blocked = dict(node('Sequence', [node('Success')]), blocked=['Reason one'])
        emitted, record = self.lower(blocked)
        self.assertEqual(([u['reason'] for u in record['unresolved']], record['unresolved'][0]['site']['path'], len(emitted)),
                         (['Reason one'], 'Root/0', 1))
        self.assertEqual(c2.family(combat.STATE + 't_state'), 'combat_dispatch')
        self.assertEqual(c2.family(combat.MANY), 'combat_dispatch')

    def test_an_emitted_wuid_behaviour_declares_its_parameter(self):
        files = {'AI/a.xml': b'<BehaviorTrees><BehaviorTree name="brawl"><Variables /><Root /></BehaviorTree>'
                             b'<BehaviorTree name="other"><Variables /><Root /></BehaviorTree></BehaviorTrees>',
                 'AI/b.xml': b'<BehaviorTrees><BehaviorTree name="plain"><Variables /><Root /></BehaviorTree></BehaviorTrees>'}
        report = dict(registrations=[dict(tree='brawl', signature='wuidData'), dict(tree='plain', signature='empty')])
        result = combat.declare_parameters(files, None, report)
        self.assertEqual(result['AI/b.xml'], files['AI/b.xml'])
        trees = {t.get('name'): t for t in E.fromstring(result['AI/a.xml'])}
        self.assertEqual([c.tag for c in trees['brawl']], ['Variables', 'Parameters', 'Root'])
        self.assertEqual(trees['brawl'].find('Parameters/Variable').attrib,
                         dict(name='data', type='_wuid', values='', isPersistent='0', form='single', requirementType='In'))
        self.assertEqual([c.tag for c in trees['other']], ['Variables', 'Root'])
        with self.assertRaises(ValueError):
            combat.declare_parameters(result, None, report)


if __name__ == '__main__': unittest.main()
