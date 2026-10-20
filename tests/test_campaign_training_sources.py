import copy
import unittest
import xml.etree.ElementTree as E

from test_campaign_training_plan import equipment
from quest_import import ast
from campaign_training_sources import resolve_equipment
from campaign_quest_bridge import UnsupportedOperation


def fixture():
    prepare, cleanup = equipment()
    doc = 'libs/ai/quests/q_example.xml'
    controller = ast(E.fromstring('''<Root><Behavior><Sequence>
        <CallBehavior Target="__object.id" BehaviorName="acquire"/>
        <Wait duration="1"/>
        <CallBehavior Target="__object.id" BehaviorName="restore"/>
        </Sequence></Behavior></Root>'''))
    model = dict(quest='q_example', behavior_documents={doc:dict(trees={
        'controller':dict(root=controller, variables=[dict(name='loan',type='common:wuid',form='single')]),
        'unrelated_tree_a':dict(root=prepare,variables=[]),
        'unrelated_tree_b':dict(root=cleanup,variables=[])})},
        controller_registration=dict(entry_points=[dict(kind='behavior_callback',name=tag,file='quests/q_example.xml',tree=tree)
            for tag, tree in [('acquire','unrelated_tree_a'),('restore','unrelated_tree_b')]]))
    return model, doc


class TrainingSourceTests(unittest.TestCase):
    def test_registration_tags_resolve_independently_of_tree_names(self):
        model, doc = fixture(); original = copy.deepcopy(model)
        resolved = resolve_equipment(model, doc, 'controller')
        self.assertEqual(resolved['prepare']['tree'], 'unrelated_tree_a')
        self.assertEqual(resolved['cleanup']['tree'], 'unrelated_tree_b')
        self.assertEqual(resolved['equipment']['leases'][0]['handle'], 'loan')
        self.assertEqual(model, original)

    def test_missing_registration_does_not_guess_a_tree(self):
        model, doc = fixture()
        model['controller_registration']['entry_points'].pop()
        with self.assertRaisesRegex(UnsupportedOperation, 'Unresolved controller callbacks'):
            resolve_equipment(model, doc, 'controller')

    def test_repeated_callsite_is_ambiguous(self):
        model, doc = fixture()
        seq = model['behavior_documents'][doc]['trees']['controller']['root']['children'][0]['children'][0]
        seq['children'].append(copy.deepcopy(seq['children'][0]))
        with self.assertRaisesRegex(UnsupportedOperation, 'unambiguous'):
            resolve_equipment(model, doc, 'controller')

    def test_conflicting_local_variable_does_not_overwrite_controller_state(self):
        model, doc = fixture()
        model['behavior_documents'][doc]['trees']['unrelated_tree_b']['variables'] = [dict(name='loan', type='_string')]
        with self.assertRaisesRegex(UnsupportedOperation, 'variable scopes'):
            resolve_equipment(model, doc, 'controller')

    def test_disconnected_editor_call_is_not_executable(self):
        model, doc = fixture()
        model['behavior_documents'][doc]['trees']['controller']['disconnected'] = [
            dict(op='CallBehavior', attributes=dict(Target='__object.id',BehaviorName='missing'), children=[])]
        self.assertEqual(resolve_equipment(model, doc, 'controller')['prepare']['name'], 'acquire')

    def test_unused_controller_message_type_is_not_an_equipment_dependency(self):
        model, doc = fixture()
        model['behavior_documents'][doc]['trees']['controller']['variables'].append(
            dict(name='unrelated_message', type='legacy:tutorialMessage', form='single'))
        self.assertEqual([v['name'] for v in resolve_equipment(model, doc, 'controller')['variables']], ['loan'])

    def test_source_assembly_resolves_real_behavior_call_sites(self):
        from campaign_training_bundle import assemble_from_source
        from campaign_behavior import BehaviorCompiler
        from campaign_dependencies import DependencyImporter
        from test_campaign_behavior import catalog
        from test_campaign_training_plan import ITEM
        from test_campaign_training_controller import EVENTS
        model, doc = fixture()
        blob = b'''<BehaviorTrees><BehaviorTree name="controller"><Variables/>
        <Root><Behavior><Sequence><CallBehavior Target="$__object.id" BehaviorName="'acquire'"/>
        <Wait duration="'1'"/><CallBehavior Target="$__object.id" BehaviorName="'restore'"/>
        </Sequence></Behavior></Root></BehaviorTree></BehaviorTrees>'''
        compiler = BehaviorCompiler([], 'Imported', catalog(), importer=DependencyImporter({}, {'items':{ITEM:ITEM}}))
        files, report = assemble_from_source(compiler, model, doc, 'controller', blob,
            'AI/imported/controller.xml', EVENTS, b'<database><EventSets/></database>')
        root = E.fromstring(files['AI/imported/controller.xml'])
        self.assertEqual(len(root.findall('.//CallBehavior')), 0)
        self.assertEqual(len(root.findall('.//CreateItem')), 1)
        self.assertEqual(len(root.findall('.//RemoveItem')), 1)
        self.assertEqual(report['source_callbacks']['prepare']['tree'], 'unrelated_tree_a')


if __name__ == '__main__': unittest.main()
