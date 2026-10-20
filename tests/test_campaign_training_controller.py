import unittest
import xml.etree.ElementTree as E

import test_campaign_training_equipment as equipment_tests
from campaign_training_controller import bind, register_events, wire_acknowledgements
from campaign_training_bundle import assemble
from campaign_behavior import BehaviorCompiler
from campaign_dependencies import DependencyImporter, ImportPlan
from test_campaign_behavior import catalog
from test_campaign_training_plan import equipment, ITEM
from campaign_quest_bridge import UnsupportedOperation


HOST = b'''<BehaviorTrees><BehaviorTree name="controller"><Variables/>
<Root><Behavior><Sequence><IncludeTree File="'source.xml'" Name="'borrow'"/>
<Wait duration="'1'"/><IncludeTree File="'source.xml'" Name="'return'"/>
</Sequence></Behavior></Root></BehaviorTree></BehaviorTrees>'''
SITES = dict(prepare=dict(file='source.xml', tree='borrow'), cleanup=dict(file='source.xml', tree='return'))
EVENTS = dict(prepare=dict(Success='Prepared', Fail='PreparationFailed'),
              cleanup=dict(Success='Cleaned', Fail='CleanupFailed'))


class TrainingControllerTests(unittest.TestCase):
    def inputs(self): return equipment_tests.TrainingEquipmentTests().lower()

    def test_single_scope_replaces_only_selected_calls_and_retains_wait(self):
        roots, variables, _ = self.inputs()
        blob, report = bind(HOST, 'controller', SITES, roots, variables, EVENTS)
        tree = E.fromstring(blob).find('BehaviorTree')
        self.assertEqual(len(tree.findall('./Variables/Variable')), 1)
        self.assertEqual(tree.find('./Variables/Variable').get('isPersistent'), '1')
        self.assertEqual([n.tag for n in tree.find('./Root/Behavior/Sequence')], ['FuseBox', 'Wait', 'FuseBox'])
        self.assertEqual(tree.find('.//CreateItem').get('CreatedItem'), tree.find('.//RemoveItem').get('Item'))
        self.assertEqual({n.get('EventName') for n in tree.findall('.//Callback_empty')},
                         {repr(n) for phase in EVENTS.values() for n in phase.values()})
        self.assertTrue(report['shared_state'])

    def test_missing_call_or_conflicting_scope_fails(self):
        roots, variables, _ = self.inputs()
        for host in (HOST.replace(b"'return'", b"'missing'"),
                     HOST.replace(b'<Variables/>', b'<Variables><Variable name="loan" type="_string"/></Variables>')):
            with self.assertRaises(UnsupportedOperation): bind(host, 'controller', SITES, roots, variables, EVENTS)

    def test_initialization_failure_is_inside_acknowledgement_wrapper(self):
        roots, variables, _ = self.inputs()
        root = E.fromstring(roots['cleanup'])
        init = E.Element('OnInit'); E.SubElement(init, 'Fail'); root.insert(0, init)
        roots['cleanup'] = E.tostring(root)
        blob, _ = bind(HOST, 'controller', SITES, roots, variables, EVENTS)
        seq = E.fromstring(blob).find('./BehaviorTree/Root/Behavior/Sequence')
        self.assertEqual(seq[2].find('Child/Sequence')[0].tag, 'Fail')
        self.assertEqual(seq[2].find('OnFail/Callback_empty').get('EventName'), "'CleanupFailed'")

    def test_dependency_outputs_are_included_and_missing_adapter_blocks_assembly(self):
        class Items:
            def plan(self, identity): return ImportPlan()
            def convert(self, identity, plan, registered):
                return ITEM, {'Libs/Tables/item/Imported.xml': b'<fixture/>'}, {}
        for available in (False, True):
            importer = DependencyImporter({'items': Items()} if available else {})
            compiler = BehaviorCompiler([], 'Imported', catalog(), importer=importer)
            args = (compiler, 'q_arbitrary', 'libs/ai/quests/q_arbitrary.xml', *equipment(),
                    [dict(name='loan',type='_wuid',form='single',values='',isPersistent='0')],
                    HOST, 'AI/imported/controller.xml', 'controller', SITES, EVENTS, b'<database><EventSets/></database>')
            if not available:
                with self.assertRaises(UnsupportedOperation): assemble(*args)
            else:
                files, report = assemble(*args)
                self.assertIn('Libs/Tables/item/Imported.xml', files)
                self.assertIn('AI/imported/controller.xml', files)
                self.assertFalse(report['publication_ready'])

    def test_event_registration_preserves_original_callbacks_and_wires_phase_events(self):
        host = HOST.replace(b'<Variables/>', b'<EditorData EventSet="original"/><Variables/>')
        registry = b'<database><EventSets><TreeEventSet Name="original"><Events><CallbackEventDefinition Name="Existing" Signature="empty" Atomic="true"/></Events></TreeEventSet></EventSets></database>'
        roots, variables, _ = self.inputs()
        blob, binding = bind(host, 'controller', SITES, roots, variables, EVENTS)
        blob, table = register_events(blob, 'controller', 'Imported_events', binding['event_signatures'], registry)
        self.assertEqual(len(E.fromstring(table).findall('.//CallbackEventDefinition')), 5)
        behavior = E.Element('EnableBehavior', Name='worker', EventSet='Imported_events')
        lifecycle = E.Element('Instance', Name='lesson')
        wire_acknowledgements(lifecycle, behavior, binding, 'Imported_events')
        self.assertEqual(lifecycle.find("Edge[@To='prepared']").get('From'), 'worker.Prepared')
        self.assertEqual(lifecycle.find("Edge[@To='cleanup_done']").get('From'), 'worker.Cleaned')
        with self.assertRaises(UnsupportedOperation): wire_acknowledgements(lifecycle, behavior, binding, 'Imported_events')


if __name__ == '__main__': unittest.main()
