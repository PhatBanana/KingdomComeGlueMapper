import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_behavior import CONTRACTS, TYPE_ADAPTERS, convert_behaviors
from campaign_dependencies import DependencyImporter, ImportPlan
from quest_import import ast
from test_campaign_quest_graph import model


def catalog():
    return dict(nodes={name:dict(attributes=list(fields), children=[]) for name,fields in CONTRACTS.items()},
                variable_types=list(TYPE_ADAPTERS.values()), enum_types=[])


def source(root, extra=None, name='q_test'):
    m = model()
    m['quest'] = name
    m['tables']['quest']['rows'][0]['quest_name'] = name
    m['behavior_documents'] = {'libs/ai/quests/' + name + '.xml': dict(trees={
        'onUpdate': dict(variables=[dict(name='hasStarted',type='_bool',values='false',isPersistent='1',form='single')],root=ast(E.fromstring(root)))})}
    m['behavior_documents'].update(extra or {})
    return m


class ItemImporter:
    def plan(self, identity): return ImportPlan(source=dict(id=identity))
    def convert(self, identity, plan, registered): return 'native-item', {'item.xml': b'<Item/>'}, {}


class CampaignBehaviorTests(unittest.TestCase):
    def test_movement_preserves_authored_references_speed_and_tolerances(self):
        m = source('''<Root><Behavior><Sequence><Move destinationSpecification="&quot;workTarget&quot;"
            speed="&quot;Walk&quot;" stopWithinDistance="&quot;0.2&quot;" stopDistanceVariation="&quot;0.1&quot;"/>
            <ExactMove destinationSpecification="&quot;nextTarget&quot;" directionSpecification="&quot;nextTarget&quot;"
            directionType="&quot;AlignWithEntity&quot;" speed="&quot;Run&quot;" precise="&quot;false&quot;"/>
            </Sequence></Behavior></Root>''')
        files, _, report = convert_behaviors([m], 'Imported', catalog())
        root = E.fromstring(next(iter(files.values())))
        self.assertEqual(root.find('.//Move').get('destinationSpecification'), '$workTarget')
        self.assertEqual(root.find('.//Move').get('speed'), 'Walk')
        self.assertEqual(root.find('.//Move').get('stopWithinDistance'), '0.2')
        self.assertEqual(root.find('.//ExactMove').get('directionSpecification'), '$nextTarget')
        self.assertEqual(report['whole_trees_emitted'], 1)

    def test_profile_activation_keeps_authored_order_and_native_fader(self):
        from test_campaign_profiles import complete_importer, HELPER
        m = source('''<Root><Sequence><FaderBarrier Fader="&quot;newGameFader&quot;" MuteSounds="&quot;true&quot;">
          <Sequence><EnableProfile profileEnable="&quot;authored_opening&quot;" profileDisable="&quot;&quot;"/>
          <Expression expressions="&quot;$hasStarted = true&quot;"/></Sequence>
          </FaderBarrier></Sequence></Root>''')
        files, bridges, report = convert_behaviors([m], 'Imported', catalog(),
            importer=complete_importer(), profile_streaming=HELPER)
        tree = E.fromstring(next(iter(files.values())))
        fader = tree.find('.//FaderBarrier')
        self.assertEqual(fader.get('Fader'), "'newGameFader'")
        self.assertEqual(fader.get('MuteSounds'), 'true')
        children = list(fader.find('Sequence'))
        self.assertTrue(children[0].tag.startswith('SendAIConceptSignal_'))
        self.assertEqual(children[1].tag, 'Expression')
        self.assertEqual(report['whole_trees_emitted'], 1)
        self.assertEqual(report['profile_modules'][0]['file'], 'Quests/Imported_profile_bridge.xml')
        self.assertIn('Quests/Imported_profile_bridge.xml', bridges)

    def test_branch_order_and_item_registration_are_preserved(self):
        for quest in ('q_test','completely_different'):
            m=source('''<Root OneTimeOnly="&quot;true&quot;" FailState="&quot;Error&quot;" saveVersion="2"><Behavior canSkip="1"><Sequence>
<IfCondition condition="&quot;!$hasStarted&quot;" failOnCondition="&quot;false&quot;"><Sequence>
<CreateItem ItemGUID="&quot;source-item&quot;" Amount="&quot;2&quot;" CreatedItem="&quot;gift&quot;" Target="&quot;__player&quot;" NotifyUI="&quot;true&quot;"/>
<EquipItem item="&quot;gift&quot;" Target="&quot;__player&quot;"/>
<Expression expressions="&quot;$hasStarted = true&quot;"/></Sequence></IfCondition>
</Sequence></Behavior></Root>''', name=quest)
            original=copy.deepcopy(m)
            importer=DependencyImporter(dict(items=ItemImporter()))
            files, _, report=convert_behaviors([m], 'Imported', catalog(), importer=importer)
            tree=E.fromstring(next(iter(files.values())))
            condition=tree.find('.//IfCondition')
            self.assertEqual(condition.get('condition'), '!$hasStarted')
            sequence=condition.find('Sequence')
            self.assertEqual([n.tag for n in sequence], ['CreateItem','EquipItem','Expression'])
            self.assertEqual(sequence[0].get('ItemGUID'), "'native-item'")
            self.assertEqual(sequence[0].get('Target'), '$__player')
            self.assertEqual(sequence[0].get('CreatedItem'), '$gift')
            self.assertEqual(report['whole_trees_emitted'], 1)
            self.assertEqual(m, original)

    def test_unsupported_child_withholds_entire_tree_and_callers(self):
        m=source('<Root><Behavior><Sequence><IncludeTree File="&quot;final/helper.xml&quot;" Name="&quot;helper&quot;"/></Sequence></Behavior></Root>',
            {'libs/ai/final/helper.xml':dict(trees={'helper':dict(variables=[],root=ast(E.fromstring(
                '<Root><Sequence><Success/><UnconvertedBranch><CreateItem ItemGUID="&quot;missing&quot;"/></UnconvertedBranch></Sequence></Root>')))})})
        files, _, report=convert_behaviors([m], 'Imported', catalog())
        self.assertFalse(files)
        self.assertEqual(report['blocked_trees'], 2)
        caller=next(t for t in report['trees'] if t['tree']=='onUpdate')
        self.assertTrue(caller['blocked_includes'])

    def test_include_uses_namespaced_converted_tree(self):
        m=source('<Root><IncludeTree File="&quot;final/helper.xml&quot;" Name="&quot;helper&quot;"/></Root>',
            {'libs/ai/final/helper.xml':dict(trees={'helper':dict(variables=[],root=ast(E.fromstring('<Root><Success/></Root>')))})})
        files, _, report=convert_behaviors([m], 'Imported', catalog())
        tree=E.fromstring(files['AI/imported/q_test/quests/q_test.xml'])
        self.assertEqual(tree.find('.//IncludeTree').get('File'), "'imported/q_test/final/helper.xml'")
        self.assertEqual(report['whole_trees_emitted'], 2)

    def test_unknown_variable_and_enum_are_not_silently_retyped(self):
        m=source('<Root><Expression expressions="&quot;$phase = $enum:MissingState.Start&quot;"/></Root>')
        m['behavior_documents']['libs/ai/quests/q_test.xml']['trees']['onUpdate']['variables'][0]['type']='custom:phase'
        files, _, report=convert_behaviors([m], 'Imported', catalog())
        self.assertFalse(files)
        self.assertEqual(len(report['trees'][0]['unresolved']), 2)

    def test_included_quest_program_keeps_its_own_owner(self):
        other=source('<Root><Success/></Root>', name='q_other')
        m=source('<Root><IncludeTree File="quests/q_other.xml" Name="onUpdate"/></Root>',
                 other['behavior_documents'])
        files, _, report=convert_behaviors([m,other], 'Imported', catalog())
        root=E.fromstring(files['AI/imported/q_test/quests/q_test.xml'])
        self.assertEqual(root.find('.//IncludeTree').get('File'), "'imported/q_other/quests/q_other.xml'")
        self.assertEqual(report['whole_trees_emitted'], 2)

    def test_authored_graph_lookup_keeps_traversal_and_filter_outputs(self):
        m = source('''<Root><Sequence><GraphSearch Origin="&quot;__land&quot;" Borders="&quot;&quot;"
depth="&quot;1&quot;" selection="&quot;true&quot;" SearchPattern="&quot;Depth&quot;"
EdgePruning="&quot;parent,inventory&quot;" AllowedEdges="&quot;&quot;" SubGraph="&quot;&quot;"
AllowSubtraph="&quot;false&quot;" includeOrigin="&quot;false&quot;" excludeOrigin="&quot;false&quot;"
failOnEmpty="&quot;true&quot;" SetOperationChoice="&quot;Intersection|And&quot;"
errorOnEmpty="&quot;false&quot;" shortCircuit="&quot;false&quot;" skipTraversed="&quot;true&quot;">
<LinkTagFilter tag="&quot;sourceQuestLink&quot;" prune="&quot;true&quot;" negprune="&quot;unknown&quot;"
Parent="&quot;&quot;" Child="&quot;initialQuestObject&quot;" Data="&quot;linkMetadata&quot;"/>
</GraphSearch><Success/></Sequence></Root>''')
        original = copy.deepcopy(m)
        files, _, report = convert_behaviors([m], 'GraphLookup', catalog())
        root = E.fromstring(next(iter(files.values())))
        sequence = root.find('.//Sequence')
        self.assertEqual([n.tag for n in sequence], ['GraphSearch', 'Success'])
        graph = sequence[0]
        self.assertEqual(graph.get('Origin'), '$__land')
        self.assertEqual(graph.get('EdgePruning'), "'parent,inventory'")
        self.assertEqual(graph.get('AllowedEdges'), '')
        self.assertEqual(graph.get('SubGraph'), '')
        self.assertEqual(graph.get('SetOperationChoice'), 'Intersection|And')
        link = graph.find('LinkTagFilter')
        self.assertEqual(link.get('tag'), "'sourceQuestLink'")
        self.assertEqual(link.get('Child'), '$initialQuestObject')
        self.assertEqual(link.get('Data'), '$linkMetadata')
        self.assertEqual(link.get('Parent'), '')
        self.assertEqual(link.get('negprune'), 'unknown')
        self.assertEqual(report['whole_trees_emitted'], 1)
        self.assertEqual(m, original)

    def test_graph_implicit_origin_and_missing_filter_are_not_guessed(self):
        m = source('''<Root><GraphSearch Origin="&quot;&quot;" failOnEmpty="&quot;false&quot;">
<LinkTagFilter tag="&quot;$tagName&quot;" Child="&quot;selected&quot;"/></GraphSearch></Root>''')
        files, _, report = convert_behaviors([m], 'GraphLookup', catalog())
        root = E.fromstring(next(iter(files.values())))
        self.assertEqual(root.find('.//GraphSearch').get('Origin'), '')
        self.assertEqual(root.find('.//LinkTagFilter').get('tag'), '$tagName')
        self.assertEqual(report['whole_trees_emitted'], 1)
        missing = catalog()
        del missing['nodes']['LinkTagFilter']
        files, _, report = convert_behaviors([m], 'GraphLookup', missing)
        self.assertFalse(files)
        self.assertEqual(report['blocked_trees'], 1)
        self.assertIn('LinkTagFilter', report['trees'][0]['unresolved'][0]['reason'])


if __name__ == '__main__': unittest.main()
