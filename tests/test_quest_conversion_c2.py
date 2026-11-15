"""Converter C2 (controller trees): source preparation, blocker ledger, golden."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_controller_contracts as contracts
import quest_controller_conversion as c2

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'quest_conversion'
KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
RETAIL = (KCD1 / 'Data/Scripts.pak').is_file() and (KCD2 / 'Data/Scripts.pak').is_file()


def node(op, children=(), **attributes):
    return dict(op=op, attributes=attributes, children=list(children), text='')


def model(callee, entry_variables, callee_variables=()):
    trees = dict(entry=dict(variables=list(entry_variables), root=node('Root')),
                 callback=dict(variables=list(callee_variables), root=node('Root', [callee])))
    return dict(quest='q_example', behavior_documents={'libs/ai/quests/q_example.xml': dict(trees=trees)})


ACTORS = dict(name='t_actors', type='common:wuid', form='associative')


class PrepareTests(unittest.TestCase):
    def test_a_callback_tree_types_a_bare_index_from_its_document(self):
        source = model(node('Send', target='t_actors[worker]', values="handle('a[b]')", code='x[y]'), [ACTORS])
        prepared, report = contracts.prepare([source])
        attrs = prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]['attributes']
        self.assertEqual(attrs, dict(target="t_actors['worker']", values="handle('a[b]')", code='x[y]'))
        self.assertEqual([r['source'] for r in report['scope_resolutions']], ['t_actors[worker]'])
        self.assertEqual(source['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]
                         ['attributes']['target'], 't_actors[worker]')
        self.assertEqual(prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['variables'], [])

    def test_an_index_is_left_alone_when_its_type_or_key_is_not_proven(self):
        cases = [([dict(ACTORS, form='array')], ()),                                   # not a string-keyed map
                 ([ACTORS, dict(name='worker', type='_string', form='single')], ()),   # a string variable could be the key
                 ([ACTORS], [dict(name='t_actors', type='_int', form='array')]),       # the tree declares it itself
                 ([], ())]                                                             # nobody declares it
        for entry, own in cases:
            prepared, report = contracts.prepare([model(node('Send', target='$t_actors[worker]'), entry, own)])
            self.assertEqual(report['scope_resolutions'], [])
        conflicting = model(node('Send', target='t_actors[worker]'), [ACTORS])
        conflicting['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['other'] = dict(
            variables=[dict(ACTORS, form='array')], root=node('Root'))
        self.assertEqual(contracts.prepare([conflicting])[1]['scope_resolutions'], [])

    def test_a_bare_key_is_a_literal_even_when_a_wuid_variable_has_its_name(self):
        worker = dict(name='worker', type='common:wuid', form='single')
        for entry, own in (([ACTORS, worker], ()), ([ACTORS], [worker]), ([], [ACTORS, worker])):
            prepared, report = contracts.prepare([model(node('Send', target='t_actors[worker]', other='$t_actors[$worker]'), entry, own)])
            attrs = prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]['attributes']
            self.assertEqual(attrs, dict(target="t_actors['worker']", other='$t_actors[$worker]'))
        other_tree = model(node('Send', target='t_actors[worker]'), [ACTORS])
        other_tree['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['other'] = dict(
            variables=[dict(name='worker', type='_string', form='single')], root=node('Root'))
        self.assertEqual(contracts.prepare([other_tree])[1]['scope_resolutions'], [])

    def test_a_bare_time_initialiser_is_quoted_as_native_ones_are(self):
        def values(variable):
            prepared, report = contracts.prepare([model(node('Success'), [variable])])
            return prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['entry']['variables'][0]['values'], report
        move = dict(name='addPars', type='additionalMoveParams', form='single')
        self.assertEqual(values(dict(move, values='destChangedThreshold(250ms)'))[0], "destChangedThreshold('250ms')")
        self.assertEqual(values(dict(move, values='destChangedThreshold(500)'))[0], "destChangedThreshold('500')")
        for untouched in ("destChangedThreshold('2s')", 'destChangedThreshold($delay)', 'continueWhenHalting(true)', ''):
            value, report = values(dict(move, values=untouched))
            self.assertEqual((value, report['initialisers']), (untouched, []))
        self.assertEqual(values(dict(move, type='_string', values='destChangedThreshold(250ms)'))[0], 'destChangedThreshold(250ms)')

    def test_an_undeclared_link_tag_converts_only_when_a_tree_writes_it(self):
        data = dict(name='linkData', type='crime:suppress', form='single')
        source = model(node('Sequence', [
            node('AddLink', From='"this.id"', To='"__player"', Tag='"suppress"', Data='"$linkData"'),
            node('AddLink', From='"this.id"', To='"__player"', Tag='"suppress"', Data='""'),
            node('AddLink', From='"this.id"', To='"__player"', Tag='"plain"', Data='""'),
            node('AddLink', From='"this.id"', To='"__player"', Tag='"$dynamic"', Data='""'),
            node('LinkTagFilter', tag='"levelOnly"'), node('RemoveLink', Tag='"removedOnly"')]), [], [data])
        self.assertEqual(contracts.prepare([source])[1]['implicit_links'],
                         dict(suppress=dict(name='suppress', type='crime:suppress'), plain=dict(name='plain')))
        mixed = model(node('Sequence', [node('AddLink', Tag='"mixed"', Data='"a"'), node('AddLink', Tag='"mixed"', Data='"b"')]), [],
                      [dict(name='a', type='one', form='single'), dict(name='b', type='two', form='single')])
        self.assertEqual(contracts.prepare([mixed])[1]['implicit_links'], dict(mixed=dict(name='mixed')))

    def test_an_engine_record_keeps_its_native_type_when_the_catalog_has_it(self):
        import campaign_behavior
        contracts.register()
        for source, target in contracts.ENGINE_TYPES.items():
            variable = dict(name='v', type=source, form='single')
            compiler = campaign_behavior.BehaviorCompiler([], 'C2', dict(nodes={}, variable_types=[target], enum_types=[]))
            self.assertEqual(compiler.variable(variable).get('type'), target)
            compiler = campaign_behavior.BehaviorCompiler([], 'C2', dict(nodes={}, variable_types=[], enum_types=[]))
            with self.assertRaises(campaign_behavior.UnsupportedOperation):
                compiler.variable(variable)

    def test_a_renamed_operation_maps_every_attribute_or_is_left_blocked(self):
        prepared, report = contracts.prepare([model(node('TurnBody', destinationSpecification='"__player"', alignWith='false'), [])])
        turned = prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]
        self.assertEqual((turned['op'], turned['source_op'], turned['attributes']),
                         ('Turn', 'TurnBody', dict(target='"__player"', align='false')))
        prepared, report = contracts.prepare([model(node('TurnBody', somethingNew='1'), [])])
        self.assertEqual(report['rename_blocked'][0]['unmapped'], ['somethingNew'])
        self.assertEqual(prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]['op'], 'TurnBody')

    def test_register_never_replaces_an_existing_contract(self):
        import campaign_behavior
        before = dict(campaign_behavior.CONTRACTS['Parallel'])
        contracts.register()
        self.assertEqual(campaign_behavior.CONTRACTS['Parallel'], before)
        self.assertEqual(campaign_behavior.CONTRACTS['GameOver'], dict(Reason='value'))


def q(value):
    return '"' + value + '"'


class LinkTypes:
    """A link-type importer with one declared data symbol."""
    source = {'questactor': dict(name='QuestActor', type='_string')}

    def plan(self, identity):
        from campaign_dependencies import ImportPlan
        return ImportPlan(source=dict(row=self.source[identity]))

    def convert(self, identity, plan, registered): return 'c2_QuestActor', {}, {}


class ContractTests(unittest.TestCase):
    """Each operation contract, through the production compiler's node lowering."""

    def lower(self, source, variables=(), registered=None, adapters=None):
        import campaign_behavior
        from campaign_dependencies import DependencyImporter
        contracts.register()
        catalog = dict(nodes={op: dict(attributes=list(fields), children=[])
                              for op, fields in campaign_behavior.CONTRACTS.items()}, variable_types=[], enum_types=[])
        prepared, report = contracts.prepare([model(source, list(variables))])
        prepared = prepared[0]['behavior_documents']['libs/ai/quests/q_example.xml']['trees']['callback']['root']['children'][0]
        compiler = campaign_behavior.BehaviorCompiler([], 'C2', catalog,
                                                      importer=DependencyImporter(adapters or {}, registered or {}))
        compiler.variables = {v['name']: v for v in variables}
        record = dict(unresolved=[], buff_dependencies=[], item_dependencies=[], includes=[])
        emitted = compiler.lower_node(prepared, 'q_example', 'libs/ai/quests/q_example.xml', 'callback', 'Root/0', record)
        return emitted, [u['reason'] for u in record['unresolved']], report

    def xml(self, *args, **kwargs):
        emitted, reasons, _ = self.lower(*args, **kwargs)
        self.assertEqual(reasons, [])
        return E.tostring(emitted, encoding='unicode')

    def blocked(self, source, *args, **kwargs):
        emitted, reasons, report = self.lower(source, *args, **kwargs)
        self.assertIsNone(emitted)
        return reasons, report

    def test_same_name_operations_keep_their_fields(self):
        self.assertEqual(self.xml(node('Look', destinationSpecification=q('__player'), destinationType='FromVariable')),
                         '<Look destinationSpecification="$__player" destinationType="FromVariable" />')
        self.assertEqual(self.xml(node('MoraleGate', [node('Success')], Target=q('this.id'), Low=q('0.000000'),
                                       High=q('0.500000'), Negation=q('true'), RunLogic=q('KeepRunning'))),
                         '<MoraleGate Target="$this.id" Low="0.000000" High="0.500000" Negation="true" '
                         'RunLogic="KeepRunning"><Success /></MoraleGate>')
        self.assertEqual(self.xml(node('AddPerceivableState', [node('Success')], PerceivableLabel=q('mercy'))),
                         """<AddPerceivableState PerceivableLabel="'mercy'"><Success /></AddPerceivableState>""")
        reasons, _ = self.blocked(node('Look', destinationSpecification=q('__player'), lookSpeed=q('1')))
        self.assertEqual(reasons, ['Unconverted attributes on Look: lookSpeed'])

    def test_a_profile_gate_names_the_converted_profile(self):
        gate = node('ProfileLoadedGate', [node('Success')], LayerName=q('q_example_attack'), NegateTo=q('false'),
                    RunLogic=q('Halt'))
        self.assertEqual(self.xml(gate, registered=dict(world_profiles={'q_example_attack': 'gm_q_example_attack'})),
                         """<ProfileLoadedGate LayerName="'gm_q_example_attack'" NegateTo="false" RunLogic="Halt">"""
                         '<Success /></ProfileLoadedGate>')
        self.assertEqual(self.blocked(gate)[0], ['Referenced world profile conversion did not complete: q_example_attack'])
        self.assertEqual(self.blocked(dict(gate, attributes=dict(gate['attributes'], LayerName=q('$layer'))))[0],
                         ['Dynamic profile identity requires runtime mapping: $layer'])

    def test_a_buff_decorator_names_the_converted_buff(self):
        buff = '8e9cb93a-eb5f-4846-be2c-2c7010872704'
        decorator = node('DecoratorBuff', [node('Success')], BuffId=q(buff), SoulWUID=q('this.id'))
        self.assertEqual(self.xml(decorator, registered=dict(buffs={buff: 'native-buff'})),
                         """<DecoratorBuff BuffId="'native-buff'" SoulWUID="$this.id"><Success /></DecoratorBuff>""")
        self.assertEqual(self.blocked(decorator)[0], ['Referenced buff conversion did not complete: ' + buff])

    def test_an_evalyzer_reads_link_data_through_the_native_symbol(self):
        name = dict(name='questName', type='_string', form='single')
        links = dict(adapters=dict(link_types=LinkTypes()))
        source = node('EvaLLyzer', Expresion=q('$questName = $QuestActor'), Quantifiers=q('Exists'), saveVersion='2')
        self.assertEqual(self.xml(source, [name], **links),
                         '<EvaLLyzer Expresion="$questName = $__link_c2_QuestActor" Quantifiers="Exists" saveVersion="2" />')
        text = node('EvaLLyzer', Expresion=q("$questName = 'the $QuestActor'"), Quantifiers=q('ForAll'), saveVersion='2')
        self.assertIn("""Expresion="$questName = 'the $QuestActor'" """, self.xml(text, [name], **links))
        self.assertEqual(self.blocked(source, [name])[0], ['Missing or ambiguous link-data symbol: QuestActor'])
        unknown = node('EvaLLyzer', Expresion=q('$questName = $Elsewhere'), Quantifiers=q('Exists'), saveVersion='2')
        self.assertEqual(self.blocked(unknown, [name], **links)[0], ['Missing or ambiguous link-data symbol: Elsewhere'])

    def test_only_a_self_teleport_is_a_teleport_action(self):
        self.assertEqual(self.xml(node('Teleport', Position=q('safeSpot'), Target=q('this.id'))),
                         '<TeleportAction Position="$safeSpot" />')
        reasons, report = self.blocked(node('Teleport', Position=q('safeSpot'), Target=q('__player')))
        self.assertEqual(reasons, ['Behavior operation needs an adapter: Teleport'])
        self.assertEqual(report['rename_blocked'][0]['reason'], 'teleport of another entity has no native action')

    def test_a_joined_animation_gate_is_a_synchronize_with_the_same_fields(self):
        fields = dict(SemaphoreCount=q('4'), InsideTimerValue=q('-1'), InvalidateOnExpire=q('false'), atomic=q('false'),
                      OutsideQueuePosVariable=q(''), InsidePosVariable=q(''), TimerType=q('GameTime'),
                      OutsideTimerValue=q('-1'), LockManagerType=q('Local'), SemaphoreName=q('scene'), RunLogic=q('Halt'))
        self.assertEqual(self.xml(node('JoinedAnimationSynchronize', [node('Success')], **fields)),
                         """<Synchronize SemaphoreCount="4" InsideTimerValue="'-1'" InvalidateOnExpire="false" """
                         """atomic="false" OutsideQueuePosVariable="" InsidePosVariable="" TimerType="GameTime" """
                         """OutsideTimerValue="'-1'" LockManagerType="Local" SemaphoreName="'scene'" RunLogic="Halt">"""
                         '<Success /></Synchronize>')
        reasons, report = self.blocked(node('JoinedAnimationSynchronize', [node('Success')], AlignTo=q('door'), **fields))
        self.assertEqual(report['rename_blocked'][0]['unmapped'], ['AlignTo'])

    def test_a_state_machine_gate_is_an_actor_state_barrier_for_a_known_state(self):
        gate = node('StateMachineGate', [node('Success')], Who=q(''), State=q('Combat'), NegateTo=q('true'),
                    RunLogic=q('KeepRunning'))
        self.assertEqual(self.xml(gate), '<ActorStateBarrier Who="" NegateTo="true" RunLogic="KeepRunning" ToState="combat">'
                                         '<Success /></ActorStateBarrier>')
        reasons, report = self.blocked(dict(gate, attributes=dict(gate['attributes'], State=q('Rider'))))
        self.assertEqual(report['rename_blocked'][0]['reason'], 'actor state has no native example: Rider')

    def test_an_install_gate_is_an_always_open_gate(self):
        gate = node('StreamingInstallGate', [node('Success')], Content=q('AdditionalContent'), RunLogic=q('KeepRunning'))
        self.assertEqual(self.xml(gate), '<IfGate atomic="false" condition="true" RunLogic="KeepRunning"><Success /></IfGate>')
        reasons, report = self.blocked(dict(gate, attributes=dict(gate['attributes'], Content=q('Disc2'))))
        self.assertEqual(report['rename_blocked'][0]['reason'], 'unknown install content: Disc2')

    def area(self, **changes):
        fields = dict(NPCs=q('__player'), Area=q("t_places['home']"), TrackIn=q('true'), TrackOut=q('false'),
                      Once=q('true'), Atomic=q('false'), OutNPC=q(''), OutEvent=q(''), ReportInitialState=q(''))
        fields.update({k: q(v) for k, v in changes.items()})
        return node('AreaPresence', [node('Success')], **fields)

    def test_area_presence_is_a_gate_once_and_a_listener_when_repeating(self):
        places = [dict(name='t_places', type='common:wuid', form='associative')]
        self.assertEqual(self.xml(self.area(), places),
                         """<AreaPresenceGate aiObjects="$__player" area="$t_places['home']" amount="AtLeastOne" """
                         'RunLogic="KeepRunning" presence="Present"><Success /></AreaPresenceGate>')
        self.assertIn('presence="NotThere"', self.xml(self.area(TrackIn='false', TrackOut='true'), places))
        self.assertEqual(self.xml(self.area(Once='false', TrackOut='true'), places),
                         """<AreaPresenceListener aiObjects="$__player" area="$t_places['home']" trackIn="true" """
                         'trackOut="true" reportInitialState="true"><Success /></AreaPresenceListener>')
        self.assertIn('<AtomicDecorator><Success /></AtomicDecorator></AreaPresenceGate>',
                      self.xml(self.area(Atomic='true'), places))
        for changes, reason in ((dict(OutEvent='event'), 'output variable has no native field: OutEvent'),
                                (dict(TrackOut='true'), 'a one-shot gate needs exactly one of TrackIn and TrackOut'),
                                (dict(Once='false', TrackIn='false'), 'nothing is tracked'),
                                (dict(Once='$once'), 'flag is not a literal boolean')):
            reasons, report = self.blocked(self.area(**changes), places)
            self.assertEqual((reasons, report['rename_blocked'][0]['reason']),
                             (['Behavior operation needs an adapter: AreaPresence'], reason))

    def guardian(self, detail, lod=None, **fields):
        fields = dict(dict(LODTerm=q('OnBoth'), StatProp=q('PropagateChild'), saveVersion='2'), **fields)
        lod = lod or node('Wait', duration=q('-1'), timeType=q('GameTime'), doFail=q('false'), variation=q(''),
                          skipInLOD=q('false'))
        return node('LODGuardian', [node('LOD', [lod], canSkip='1'), node('Detail', [detail], canSkip='1')], **fields)

    def test_a_waiting_lod_guardian_is_a_detail_barrier(self):
        self.assertEqual(self.xml(self.guardian(node('Success'))),
                         '<DetailBehaviorBarrier RunLogic="Halt"><Success /></DetailBehaviorBarrier>')
        self.assertEqual(self.xml(self.guardian(node('LODLock', [node('Success')]))),
                         '<DetailBehaviorBarrier RunLogic="KeepRunning"><Success /></DetailBehaviorBarrier>')
        self.assertEqual(self.xml(self.guardian(node('Success'), StatProp=q('FailAlways'))),
                         '<Sequence><DetailBehaviorBarrier RunLogic="Halt"><Success /></DetailBehaviorBarrier><Fail /></Sequence>')
        reasons, report = self.blocked(self.guardian(node('Success'), lod=node('Success')))
        self.assertEqual(report['rename_blocked'][0]['reason'], 'the LOD branch does more than wait')
        self.assertEqual(reasons, [contracts.RESIDUE[op] for op in ('LODGuardian', 'LOD', 'Detail')])
        reasons, report = self.blocked(self.guardian(node('Success'), LODTerm=q('OnLOD')))
        self.assertEqual(report['rename_blocked'][0]['reason'], 'unknown LODTerm or StatProp')

    def test_an_operation_without_a_native_equivalent_gets_a_typed_reason(self):
        for op, kind, status in (('FinishPatch', 'daycycle_lifecycle', 'open'),
                                 ('AddOpponent', 'op_inexpressible', 'inexpressible'),
                                 ('MakeMeIdle', 'op_inexpressible', 'inexpressible'), ('SetOwner', 'op_partial', 'open'),
                                 ('DrawWeapon', 'op_partial', 'open'), ('NeverHeardOf', 'op_no_contract', 'open')):
            reasons, _ = self.blocked(node(op))
            self.assertEqual(reasons, [contracts.RESIDUE.get(op, 'Behavior operation needs an adapter: ' + op)])
            self.assertEqual((c2.family(reasons[0]), c2.STATUS.get(c2.family(reasons[0]), 'open')), (kind, status))
        self.assertEqual({c2.family(reason) for reason in contracts.RESIDUE.values()},
                         {'daycycle_lifecycle', 'op_inexpressible', 'op_partial'})

    def test_every_rewrite_target_and_hook_has_a_contract(self):
        import campaign_behavior
        contracts.register()
        for target in ('TeleportAction', 'ActorStateBarrier', 'IfGate', 'AreaPresenceGate', 'AreaPresenceListener',
                       'DetailBehaviorBarrier', 'Synchronize', 'Turn', 'AtomicDecorator', 'Sequence', 'Fail'):
            self.assertIn(target, campaign_behavior.CONTRACTS)
        self.assertEqual(set(contracts.POST) - set(contracts.CONTRACTS), set())
        self.assertEqual(set(contracts.RESIDUE) & set(contracts.CONTRACTS), set())


class LedgerTests(unittest.TestCase):
    def run_(self, unresolved, emitted_root):
        source = model(node('Success'), [])
        document = 'libs/ai/quests/q_example.xml'
        del source['behavior_documents'][document]['trees']['entry']
        tree = E.Element('BehaviorTree', name='callback'); E.SubElement(tree, 'Variables'); tree.append(emitted_root)
        record = dict(document=document, tree='callback', unresolved=unresolved, native_emitted=not unresolved)
        return dict(model=source, prepared=dict(scope_resolutions=[], renamed=[], rename_blocked=[]),
                    behaviors={} if unresolved else {'AI/x.xml': E.tostring(tree)}, conversion=dict(trees=[record]))

    def test_an_emitted_tree_must_keep_the_source_shape(self):
        good = E.Element('Root'); E.SubElement(good, 'Success')
        led = c2.ledger(self.run_([], good))
        self.assertEqual(led['layers']['source_equivalence']['summary'],
                         dict(checked=1, passed=1, failed=0, residue=0, nodes_compared=2, rewritten_nodes=0))
        for broken in (E.Element('Root'), E.fromstring('<Root><Fail/></Root>')):
            self.assertEqual(c2.ledger(self.run_([], broken))['layers']['source_equivalence']['verdict'], 'FAIL')

    def test_blockers_are_counted_by_reason_and_family(self):
        sites = [dict(reason='Behavior operation needs an adapter: X')] * 2 + [dict(reason='Referenced buff conversion did not complete: g')]
        led = c2.ledger(self.run_(sites, E.Element('Root')))
        self.assertEqual(led['trees'], dict(total=1, blocked=1))
        self.assertEqual([(b['family'], b['sites'], b['status']) for b in led['blockers']],
                         [('op_no_contract', 2, 'open'), ('buff', 1, 'needs_importer')])
        self.assertIn('| Behavior operation needs an adapter: X | op_no_contract | 2 | 1 | open |', c2.markdown(led))


@unittest.skipUnless(RETAIL, 'requires installed retail KCD1 and KCD2 scripts')
class RetailTests(unittest.TestCase):
    def test_q_skalitz_matches_its_golden_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = c2.ledger(c2.convert(KCD1, KCD2, 'q_skalitz', Path(tmp) / 'work',
                                       ['q_tutorials', 'q_tutorial_swordOne', 'q_escapeToTalmberk']))
        self.assertEqual(led['layers']['source_equivalence']['failures'], [])
        self.assertEqual(json.loads(json.dumps(c2.golden(led), sort_keys=True)),
                         json.loads((FIXTURES / 'q_skalitz.c2.golden.json').read_text(encoding='utf-8')))


if __name__ == '__main__': unittest.main()
