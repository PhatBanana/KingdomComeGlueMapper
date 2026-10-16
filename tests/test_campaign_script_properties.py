import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_script_properties import misc_properties, upgrade_reads
from campaign_dependency_adapters import EntityAdapter
from campaign_dependencies import DependencyImporter
from campaign_trigger_areas import write_areas
from campaign_entity_links import native_guid
from quest_import import ast
from test_campaign_behavior import source, catalog
from campaign_behavior import convert_behaviors


PROGRAM = """local soEntity = XGenAIModule.GetEntityByWUID(data.__object.id)
data.editorDuration = GetEntityScriptProperty(soEntity, 'waitDuration') or ''
data.editorVariation = GetEntityScriptProperty(soEntity, 'waitVariation') or '0s'"""


class ScriptPropertyTests(unittest.TestCase):
    def test_slot_animation_property_reads_keep_entity_id_lookup(self):
        program = "local obj = XGenAIModule.GetEntityIdByWUID(data.__object.id); data.pickingParameters.animationPick = GetEntityMiscProperty(obj, 'animationPick') or ''; data.pickingParameters.tagsPick = GetEntityMiscProperty(obj, 'tagsPick') or ''"
        expected = program.replace('GetEntityMiscProperty', 'EntityUtils.GetMiscProperty')
        self.assertEqual(upgrade_reads(program, False, True), expected)
        self.assertIsNone(upgrade_reads(program, True, False))
        self.assertIsNone(upgrade_reads(program.replace('GetEntityIdByWUID', 'GetEntityByWUID'), True, True))
        self.assertIsNone(upgrade_reads(program.replace('GetEntityMiscProperty', 'GetEntityScriptProperty'), True, True))
        self.assertIsNone(upgrade_reads(program + '; entity:Attack()', True, True))
        root = E.Element('Root')
        E.SubElement(root, 'ExecuteLua', code='"' + program + '"')
        native = catalog()
        native['nodes']['ExecuteLua'] = dict(attributes=['code'], children=[])
        native['native_misc_property_reader'] = True
        files, _, report = convert_behaviors([source(E.tostring(root, encoding='unicode'))], 'Imported', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        self.assertEqual(E.fromstring(next(iter(files.values()))).find('.//ExecuteLua').get('code'), expected)

    def test_complete_lookup_program_retains_defaults_and_order(self):
        converted = upgrade_reads(PROGRAM, True)
        self.assertEqual(converted, PROGRAM.replace('GetEntityScriptProperty', 'EntityUtils.GetScriptProperty').replace('\n', '; '))
        root = E.Element('Root')
        E.SubElement(root, 'ExecuteLua', code='"' + PROGRAM + '"')
        native = catalog()
        native['nodes']['ExecuteLua'] = dict(attributes=['code'], children=[])
        native['native_script_property_reader'] = True
        files, _, report = convert_behaviors([source(E.tostring(root, encoding='unicode'))], 'Imported', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        self.assertEqual(E.fromstring(next(iter(files.values()))).find('.//ExecuteLua').get('code'), converted)

    def test_unknown_calls_and_scope_changes_are_not_silently_dropped(self):
        for script in (PROGRAM + '; entity:Attack()', PROGRAM.replace('soEntity,', 'unknown,'),
                       PROGRAM.replace("'waitDuration'", 'data.key'),
                       PROGRAM.replace("or '0s'", 'or data.fallback'),
                       PROGRAM.replace('local soEntity', 'local entity')):
            self.assertIsNone(upgrade_reads(script, True))
        self.assertIsNone(upgrade_reads(PROGRAM, False))

    def test_property_precedence_and_unrepresentable_values(self):
        self.assertEqual(misc_properties({'Misc': '|waitDuration:1|waitDuration:2|enabled:false',
                                          'waitDuration': '3', 'waitVariation': '0s'}),
                         'waitDuration:3|enabled:false|waitVariation:0s')
        for props in ({'Misc': 'missing'}, {'Misc': 'a:'}, {'bad|key': 'x'}, {'a': 'x|y'}, {'a': ''}):
            with self.assertRaises(ValueError): misc_properties(props)

    def test_entity_import_preserves_authored_work_settings(self):
        entity = E.fromstring('<Entity EntityGuid="123456789abcdef0" EntityClass="SmartObjectHolder" Name="work" Pos="1,2,3"><Properties><Script Misc="waitDuration:1" waitDuration="5s" waitVariation="2s"/></Properties></Entity>')
        world = dict(entities={'work': dict(source='layers/work.xml', attributes=dict(entity.attrib), entity=ast(entity))})
        adapter = EntityAdapter(world, E.Element('Root'), write_areas([], 10), 10)
        importer = DependencyImporter({'entities': adapter})
        identity = native_guid(int('123456789abcdef0', 16))
        self.assertEqual(importer.ensure('entities', identity), identity)
        entity_files = [blob for blob in importer.files.values() if b'SmartObjectHolder' in blob]
        self.assertEqual(len(entity_files), 1)
        script = E.fromstring(entity_files[0]).find('.//Script')
        self.assertEqual(script.attrib, {'Misc': 'waitDuration:5s|waitVariation:2s'})


if __name__ == '__main__': unittest.main()
