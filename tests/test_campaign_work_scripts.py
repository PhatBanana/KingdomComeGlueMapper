import unittest
import xml.etree.ElementTree as E
from test_campaign_behavior import source, catalog
from campaign_work_scripts import upgrade
from campaign_behavior import convert_behaviors


class WorkScriptTests(unittest.TestCase):
    def test_property_local_and_source_branches_are_preserved(self):
        program = '''local place = XGenAIModule.GetEntityByWUID(data.workplace)
          local roof = GetEntityScriptProperty(place, 'sheltered')
          if roof == 'yes' then data.sheltered = true
          elseif roof == 'no' then data.sheltered = false
          else data.sheltered = data.previous end'''
        self.assertIsNone(upgrade(program, {}))
        result = upgrade(program, {'native_script_property_reader': True})
        self.assertIn('EntityUtils . GetScriptProperty ( place ,', result)
        self.assertIn('elseif roof ==', result)
        self.assertIn('else data . sheltered = data . previous', result)
        self.assertNotIn('GetEntityScriptProperty', result)

    def test_generic_data_math_and_string_program(self):
        result = upgrade('''data.count = data.count - 1
          if data.count < 1 then data.intensity = 0
          elseif data.count < 5 then data.intensity = 0.3
          else data.intensity = 1 end
          data.duration = tostring(data.wait) .. 's' ''', {})
        self.assertIsNotNone(result)
        self.assertIn("tostring ( data . wait ) .. 's'", result)

    def test_gate_uses_same_converter_without_losing_return(self):
        program = "local obj = XGenAIModule.GetEntityByWUID(data.obj); local value = GetEntityScriptProperty(obj, 'roof'); if value then return true else return false end"
        element = E.Element('Root')
        E.SubElement(element, 'LuaGate', code=program, saveVersion='2')
        model = source(E.tostring(element, encoding='unicode'))
        native = catalog(); native['native_script_property_reader'] = True
        files, _, report = convert_behaviors([model], 'Work', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        converted = E.fromstring(next(iter(files.values()))).find('.//LuaGate').get('code')
        self.assertIn('return true', converted)
        self.assertIn('return false', converted)

    def test_unknown_calls_and_incomplete_programs_fail_whole_conversion(self):
        programs = [
            'data.count = data.count + 1; Unknown.GameplayEffect()',
            "entity.soul:AddMetaRoleByName('some_role')",
            'data.x = math.random()', 'data.x = unknown',
            'local data = 1', 'local entity = data.id',
            'local GetEntityScriptProperty = 1', 'local GetEntityMiscProperty = 1',
            'local while = 1', 'data.end = 1',
            "local obj = data.id; data.x = GetEntityScriptProperty(obj, 'roof')",
            "if true then local x = 1 end data.x = x",
            'if true then data.x = 1', 'return true; data.x = 1',
            "local a = XGenAIModule.GetEntityByWUID(data.id); data.x = GetEntityMiscProperty(a, 'roof')",
        ]
        for program in programs:
            with self.subTest(program=program):
                self.assertIsNone(upgrade(program, {'native_script_property_reader': True,
                                                  'native_misc_property_reader': True}))


if __name__ == '__main__': unittest.main()
