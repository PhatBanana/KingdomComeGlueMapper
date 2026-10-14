import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_conditions import QuestConditions
from campaign_dialogue_runtime import attach_dialogue


class AreaConditionsTests(unittest.TestCase):
    def test_native_context_preserves_index_and_requires_converted_identities(self):
        compiler = QuestConditions([], context_entities={
            'IsActor': {'source_person': 'converted_person'},
            'IsActorInside': {'old_yard': 'converted_yard'}})
        self.assertEqual(compiler.compile("IsActor('source_person')[0]"), "IsActor('converted_person')[0]")
        self.assertEqual(compiler.compile("IsActorInside('old_yard')[1]"), "IsActorInside('converted_yard')[1]")
        for text in ("IsActor('missing')[0]", "IsActorInside('old_yard')[other]", "IsActorInside('missing')[1]"):
            with self.assertRaises(ValueError): compiler.compile(text)
        self.assertEqual(compiler.bindings, {})

    def compiler(self):
        return QuestConditions([], participant_assets={'1': 'debtor'},
                               area_assets={'source_yard': 'yard'})

    def test_location_condition_retains_negation_and_explicit_actor_binding(self):
        compiler = self.compiler()
        result = compiler.compile("!IsActorInside('source_yard')[1]")
        self.assertTrue(result.startswith('!('))
        self.assertEqual(list(compiler.bindings.values()),
                         [dict(kind='area_check', asset='debtor', area='yard')])

    def test_unknown_area_context_or_trailing_expression_cannot_emit_partial_ports(self):
        for expression in ("IsActorInside('other')[1]", "IsActorInside('source_yard')[0]",
                           "IsActorInside('source_yard')", "IsActorInside('source_yard')[1] AND Unknown()"):
            compiler = self.compiler()
            with self.assertRaises(ValueError): compiler.compile(expression)
            self.assertEqual(compiler.bindings, {})

    def test_nested_sequence_availability_retains_area_dependencies(self):
        compiler = self.compiler()
        compiler.sequences['4'] = dict(source={}, entry=dict(
            entry_condition="IsActorInside('source_yard')[1]"))
        compiler.compile('IsSeqAvailable(4)')
        self.assertEqual(next(iter(compiler.bindings.values()))['area'], 'yard')

    def test_native_area_query_uses_registered_assets_and_live_output(self):
        compiler = self.compiler()
        compiler.compile("IsActorInside('source_yard')[1]")
        port = next(iter(compiler.bindings))
        files = {
            'project.xml': b'<Database><Skald><Project Name="project"><Definitions><Definition File="quest.xml"/></Definitions><Nodes><quest Name="quest"/></Nodes><Assets><Asset Name="debtor" Target="Soul"/><Asset Name="yard" Target="Area"/></Assets></Project></Skald></Database>',
            'quest.xml': b'<Database><Skald><Quest Name="quest"><Ports><Port Name="ready" Direction="Out" Type="bool"/></Ports></Quest></Skald></Database>'}
        blob = ('<Database><Skald><FaderDialog Name="conversation"><Ports>'
                '<Port Name="active" Direction="In" Type="bool"/>'
                f'<Port Name="{port}" Direction="In" Type="bool"/>'
                '</Ports></FaderDialog></Skald></Database>').encode()
        report = dict(actions={}, active_port='active', conditions=compiler.bindings)
        result = attach_dialogue(files, 'project', blob, report, 'quest.ready', 'project.xml')
        root = E.fromstring(result['project.xml'])
        query = root.find('.//Function')
        self.assertEqual(query.get('MethodName'), 'wh::rpgmodule::AreaCheck')
        self.assertEqual({n.get('Name'):n.get('Alias') for n in query.findall('Asset')},
                         {'Souls':'debtor', 'Areas':'yard'})
        self.assertIsNotNone(root.find(f".//conversation/Edge[@From='{query.get('Name')}.IsInside']"))
        files['project.xml'] = files['project.xml'].replace(b'Target="Area"', b'Target="Soul"')
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            attach_dialogue(files, 'project', blob, report, 'quest.ready', 'project.xml')


if __name__ == '__main__':
    unittest.main()
