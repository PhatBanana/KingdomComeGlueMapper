import sys
from pathlib import Path
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_person import resolve_link_targets


class PersonLinkTests(unittest.TestCase):
    def test_cross_layer_target_is_resolved_and_hashed(self):
        actor = ET.fromstring('<Entity EntityId="1"><EntityLinks><Link TargetId="2" Name="Home"/></EntityLinks></Entity>')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'level.pak'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('layers/home.xml', '<Objects><Entity EntityId="2" Name="OriginalHome"/></Objects>')
            with zipfile.ZipFile(path) as z:
                evidence = {}
                result = resolve_link_targets(z, actor, [actor], evidence)
                self.assertEqual(result[1].get('Name'), 'OriginalHome')
                self.assertEqual(len(evidence['layers/home.xml']), 64)
            with zipfile.ZipFile(path, 'a') as z:
                z.writestr('layers/duplicate.xml', '<Objects><Entity EntityId="2" Name="DifferentHome"/></Objects>')
            with zipfile.ZipFile(path) as z:
                with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                    resolve_link_targets(z, actor, [actor], {})

    def test_missing_link_is_not_discarded(self):
        actor = ET.fromstring('<Entity><EntityLinks><Link TargetId="7"/></EntityLinks></Entity>')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'level.pak'
            with zipfile.ZipFile(path, 'w'): pass
            with zipfile.ZipFile(path) as z:
                with self.assertRaisesRegex(ValueError, 'Unresolved'):
                    resolve_link_targets(z, actor, [actor], {})


if __name__ == '__main__': unittest.main()
