import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from build_campaign_initial_loadout import merge_item_strings


class LoadoutLocalizationTests(unittest.TestCase):
    def test_shared_keys_in_another_table_are_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'locale.pak'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('text_ui_items.xml','<Table></Table>')
                z.writestr('other.xml','<Table><Row><Cell>shared</Cell><Cell>Trousers</Cell><Cell>Trousers</Cell></Row></Table>')
            with zipfile.ZipFile(path) as z:
                additions = ET.fromstring('<Table><Row><Cell>shared</Cell><Cell>Trousers</Cell><Cell>Trousers</Cell></Row><Row><Cell>new</Cell><Cell>New</Cell><Cell>New</Cell></Row></Table>')
                result = ET.fromstring(merge_item_strings(z, additions))
                self.assertEqual([r.findtext('Cell') for r in result], ['new'])
                additions[0][1].text = 'Conflicting text'
                with self.assertRaises(ValueError): merge_item_strings(z, additions)


if __name__ == '__main__': unittest.main()
