import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from probe_activation import reconcile
from lighting_cubemaps import TARGET_TIMES


class ProbeActivationTests(unittest.TestCase):
    def fixture(self, source_active='1', dynamic='1'):
        source = ET.fromstring(f'<Entity EntityId="42"><Properties bActive="{source_active}"/></Entity>')
        root = ET.fromstring(f'''<Objects><Entity Name="gm_lighting_42" EntityClass="EnvironmentLight">
          <Properties bActive="0" BoxSizeZ="5"><Options SortPriority="11"/>
          <OptionsAdvanced bDynamic="{dynamic}" texture_deferred_cubemap=""/></Properties>
          <EntityLinks><Link TargetId="99"/></EntityLinks></Entity></Objects>''')
        return root, source

    def test_complete_dynamic_bake_only_changes_activation_and_is_idempotent(self):
        root, source = self.fixture()
        before = ET.tostring(root)
        validated = []
        report = reconcile(root, [source], validated.append)
        self.assertEqual(report['restored_count'], 1)
        self.assertEqual(len(validated), 2*len(TARGET_TIMES))
        self.assertEqual(ET.tostring(root), before.replace(b'bActive="0"', b'bActive="1"'))
        self.assertEqual(reconcile(root, [source], validated.append)['restored_count'], 0)

    def test_missing_time_or_diffuse_sample_keeps_disabled(self):
        root, source = self.fixture()
        def missing(path):
            if path.endswith('/13_00_cm_diff.dds'):
                raise KeyError(path)
        self.assertEqual(reconcile(root, [source], missing)['restored_count'], 0)
        self.assertEqual(root.find('Entity/Properties').get('bActive'), '0')

    def test_missing_bake_and_source_disabled_and_deferred_layer_stay_disabled(self):
        for active, dynamic, selected in [('1', '0', True), ('0', '1', True), ('1', '1', False)]:
            root, source = self.fixture(active, dynamic)
            before = ET.tostring(root)
            report = reconcile(root, [source] if selected else [], lambda path: self.fail(path))
            self.assertEqual(report['restored_count'], 0)
            self.assertEqual(before, ET.tostring(root))

    def test_invalid_cube_is_not_activated(self):
        root, source = self.fixture()
        def invalid(path):
            raise ValueError('Unexpected cubemap tail or missing mips')
        self.assertEqual(reconcile(root, [source], invalid)['restored_count'], 0)


if __name__ == '__main__':
    unittest.main()
