import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_path_parameters import DEFAULTS, native_fields, convert
from campaign_behavior import convert_behaviors
from test_campaign_behavior import source, catalog


class PathParameterTests(unittest.TestCase):
    def test_source_defaults_and_overrides_are_explicit(self):
        text = convert('usePaths(false), useDoorPortals(true)', DEFAULTS)
        self.assertIn('usePaths(false)', text)
        self.assertIn('useDoorPortals(true)', text)
        self.assertIn('autoAllowedSmartObjects(true)', text)
        self.assertIn('enableSecondTryWithGenNSO(true)', text)
        self.assertIn('useGeneratedNSO(false)', text)
        self.assertEqual(text.count('('), 6)
        for value in ('usePaths(1)', 'unknown(true)', 'usePaths(false),usePaths(true)', 'usePaths(false);Attack()'):
            with self.assertRaises(ValueError): convert(value, DEFAULTS)
        with self.assertRaises(ValueError): convert('', ['usePaths'])

    def test_evidence_requires_typed_native_variable(self):
        tree = E.fromstring('<BehaviorTree><Variables><Variable name="route" type="pathFindingParams" values="usePaths(false)"/><Variable name="other" type="unrelated"/></Variables><Root><Sequence><Expression expressions="$route.useDoorPortals = true, $other.unknown = false, $routeFake.fake = true"/></Sequence></Root></BehaviorTree>')
        self.assertEqual(native_fields(tree), {'usePaths', 'useDoorPortals'})

    def test_behavior_preserves_policy_and_requires_native_members(self):
        model = source('<Root><Success/></Root>')
        tree = next(iter(model['behavior_documents'].values()))['trees']['onUpdate']
        tree['variables'].append(dict(name='routePolicy', type='pathFindingParams', values='usePaths(false)', form='single'))
        native = catalog()
        native['variable_types'].append('pathFindingParams')
        self.assertFalse(convert_behaviors([model], 'Imported', native)[0])
        native['path_parameter_fields'] = list(DEFAULTS)
        files, _, report = convert_behaviors([model], 'Imported', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        var = E.fromstring(next(iter(files.values()))).find(".//Variable[@name='routePolicy']")
        self.assertEqual(var.get('type'), 'pathFindingParams')
        self.assertEqual(var.get('values'), convert('usePaths(false)', DEFAULTS))


if __name__ == '__main__': unittest.main()
