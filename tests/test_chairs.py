from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from chairs import convert, DONOR
from region_travel import guid
from test_cooking_pots import archive


SOURCE = b'''<Objects><Entity EntityId="1" EntityClass="Chair" Pos="10,20,30"
 Rotate="0.707106781,0,0,0.707106781"><Properties object_Model="original.cgf"/></Entity>
 <Entity EntityId="2" EntityClass="Chair" Layer="quest_state1{x}"><Properties object_Model="later.cgf"/></Entity>
 <Entity EntityId="3" EntityClass="GeomEntity"><Properties object_Model="original.cgf"/></Entity></Objects>'''


def native():
    root = E.Element('Objects')
    owner = E.SubElement(root, 'Entity', EntityId=DONOR, EntityClass='StanceSmartObject', Pos='100,200,300')
    E.SubElement(owner, 'Properties', soclass_SmartObjectHelpers='Sit_1Place_Chair_Low', guidSmartObjectType='native')
    links = E.SubElement(owner, 'EntityLinks')
    for key, role, cls in [('50', 'attachable', 'Chair'), ('51', 'chairPointIn', 'TagPoint'),
                           ('52', 'chairPointOut', 'TagPoint'), ('53', '', 'ActionTrigger')]:
        node = E.SubElement(root, 'Entity', EntityId=key, EntityClass=cls, Pos='101,200,300' if key == '53' else '100,200,300', EditorLayer='Trosky')
        props = E.SubElement(node, 'Properties')
        E.SubElement(links, 'Link', TargetId=key, Name=role)
        if cls == 'ActionTrigger':
            E.SubElement(props, 'Click', UseMessage='@ui_use_sit')
            E.SubElement(E.SubElement(node, 'EntityLinks'), 'Link', TargetId=DONOR, Name='')
    E.SubElement(links, 'Link', TargetId='999', Name='oppositeNeighbor')
    return E.tostring(root)


class ChairTests(unittest.TestCase):
    def build(self, files=None, incremental=False):
        if files is None:
            files = {'objects_mission0.xml': b'<Objects><Entity EntityId="100" Name="keep"/>'
                     b'<Entity Name="glue_item_1" Geometry="converted.cgf" Material="original.mtl"/>'
                     b'<Entity Name="glue_item_3" Geometry="decorative.cgf"/></Objects>'}
        with archive({'objects_mission0.xml': SOURCE}) as source, archive({'objects_mission0.xml': native(),
                'smartobjecthelpersetanimations.xml': b'<SmartObjectAnimationCollections><Collection HelperSetName="Sit_1Place_Chair_Low"/></SmartObjectAnimationCollections>'}) as donor:
            return convert(files, source, donor, guid, incremental=incremental)

    def test_full_native_contract_with_no_external_links(self):
        files, report = self.build()
        nodes = [e for e in E.fromstring(files['objects_mission0.xml']).iter('Entity') if e.get('Name', '').startswith('gm_chair_')]
        self.assertEqual(len(nodes), 5)
        ids = {e.get('EntityId'): e.get('EntityGuid') for e in nodes}
        for node in nodes:
            self.assertNotIn('EditorLayer', node.attrib)
            for link in node.findall('EntityLinks/Link'):
                self.assertEqual(ids[link.get('TargetId')], link.get('TargetGuid'))
        trigger = next(e for e in nodes if e.get('EntityClass') == 'ActionTrigger')
        self.assertEqual(trigger.find('Properties/Click').get('UseMessage'), '@ui_use_sit')
        self.assertEqual(trigger.get('Pos'), '10,21,30')
        self.assertEqual(trigger.find('EntityLinks/Link').get('Name'), '')
        definitions = {e.text for e in E.fromstring(files['waitinglinks.xml']).iter('LinkDefinition')}
        self.assertEqual(definitions, {'attachable', 'chairPointIn', 'chairPointOut'})

    def test_geometry_preserved_and_only_active_authored_chairs_upgraded(self):
        files, report = self.build()
        nodes = list(E.fromstring(files['objects_mission0.xml']).iter('Entity'))
        chair = next(e for e in nodes if e.get('EntityClass') == 'Chair')
        self.assertEqual(chair.find('Properties').get('object_Model'), 'converted.cgf')
        self.assertEqual(chair.get('Material'), 'original.mtl')
        self.assertEqual(chair.get('Pos'), '10,20,30')
        self.assertNotIn('glue_item_1', [e.get('Name') for e in nodes])
        self.assertIn('glue_item_3', [e.get('Name') for e in nodes])
        self.assertEqual(report['converted'], 1)
        self.assertEqual(report['inactive_layer_chairs'][0]['source_id'], '2')

    def test_missing_geometry_fails_before_producing_invisible_chair(self):
        with self.assertRaisesRegex(ValueError, 'geometry is missing'):
            self.build({'objects_mission0.xml': b'<Objects/>'})

    def test_incremental_preserves_complete_chair_and_rejects_partial(self):
        files, _ = self.build()
        again, report = self.build(files, incremental=True)
        self.assertEqual(report['converted'], 0)
        self.assertEqual(again['objects_mission0.xml'], files['objects_mission0.xml'])
        root = E.fromstring(files['objects_mission0.xml'])
        root.remove(next(e for e in root if e.get('EntityClass') == 'ActionTrigger'))
        files['objects_mission0.xml'] = E.tostring(root)
        with self.assertRaisesRegex(ValueError, 'Incomplete seating'):
            self.build(files, incremental=True)

    def test_duplicate_conversion_rejected(self):
        files, _ = self.build()
        with self.assertRaisesRegex(ValueError, 'already converted'):
            self.build(files)


if __name__ == '__main__': unittest.main()
