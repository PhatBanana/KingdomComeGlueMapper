from contextlib import contextmanager
import tempfile
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from cooking_pots import convert, inventory, fire_pivot, CONTRACT, DONORS
from region_travel import guid


@contextmanager
def archive(files):
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
        path = Path(directory)/'fixture.pak'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in files.items(): z.writestr(name, data)
        with zipfile.ZipFile(path) as z: yield z


def source_world():
    return b'''<Objects>
      <Entity EntityId="1" EntityClass="SmartObjectHolder" Pos="10,20,30" Rotate="0.707106781,0,0,0.707106781">
        <Properties soclasses_SmartObjectHelpers="Fireplace_camp"/>
        <EntityLinks><Link Name="st_kettle" TargetId="2"/><Link Name="fireProcedural['fire_medium']" TargetId="3"/>
        <Link TargetId="4"/><Link TargetId="6"/></EntityLinks></Entity>
      <Entity EntityId="2" EntityClass="SequenceTrigger" Pos="10,21,31">
        <Properties><Click UseMessage="@ui_eat_kettle"/><Hold InventoryFilter="food.*.apple|potion.*.*"/></Properties>
        <EntityLinks><Link TargetId="1"/></EntityLinks></Entity>
      <Entity EntityId="3" EntityClass="ProceduralObject" Pos="10,20,30.1"/>
      <Entity EntityId="4" EntityClass="ItemSlot"><Properties sWH_AI_EntityCategory="spoon"/>
        <EntityLinks><Link TargetId="5"/></EntityLinks></Entity>
      <Entity EntityId="6" EntityClass="ItemSlot"><Properties sWH_AI_EntityCategory="Bowl"/>
        <EntityLinks><Link TargetId="7"/></EntityLinks></Entity>
      </Objects>'''


def inset_hearth():
    """A black-kitchen hearth: the flame origin sits above the pot resting on the grate."""
    return b'''<Objects>
      <Entity EntityId="1" EntityClass="SmartObjectHolder" Pos="820.8,3487.6,52.28" Rotate="0.6756,0,0,-0.7373">
        <Properties soclasses_SmartObjectHelpers="Fireplace_CernaKuchyn"/>
        <EntityLinks><Link Name="st_kettle" TargetId="2"/><Link Name="st_fire" TargetId="10"/>
        <Link Name="fireProcedural[('fireplace_inset')]" TargetId="3"/>
        <Link TargetId="8"/><Link TargetId="9"/></EntityLinks></Entity>
      <Entity EntityId="2" EntityClass="SequenceTrigger" Pos="821.2074,3487.3896,52.046768">
        <Properties><Click UseMessage="@ui_eat_kettle"/><Hold InventoryFilter="food.*.apple"/></Properties>
        <EntityLinks><Link TargetId="1"/></EntityLinks></Entity>
      <Entity EntityId="10" EntityClass="SequenceTrigger" Pos="821.30389,3486.9893,52.046768" Rotate="0.99144495,0,0,0.13052586">
        <Properties><Click UseMessage="@ui_cook_item"/><Hold UseMessage="@ui_use_fire"/></Properties>
        <EntityLinks><Link TargetId="1"/></EntityLinks></Entity>
      <Entity EntityId="3" EntityClass="ProceduralObject" Pos="821.21039,3487.7664,52.199142" Rotate="0.3535535,-0.35355353,-0.61237234,0.6123724"/>
      <Entity EntityId="8" EntityClass="PickableItem" Pos="821.22852,3487.3599,52.088318">
        <Properties sWH_AI_EntityCategory="Kotlik"/></Entity>
      <Entity EntityId="9" EntityClass="PickableItem" Pos="821.045,3487.115,52.116516">
        <Properties sWH_AI_EntityCategory="Naberacka"/></Entity>
      </Objects>'''


def native_world():
    root = E.Element('Objects')
    for kind, key in DONORS.items():
        owner = E.SubElement(root, 'Entity', EntityId=key, EntityClass='FireplaceSmartObject', Pos='100,200,300')
        E.SubElement(owner, 'Properties', guidSmartObjectType='native-type')
        links = E.SubElement(owner, 'EntityLinks')
        for index, name in enumerate(CONTRACT, 1):
            target = str(int(key) + index)
            cls = ('KettleActionTrigger' if index == 1 else 'FoodProcessingTrigger' if index == 2
                   else 'ItemSlot' if index == 3 else 'RuntimePrefab')
            node = E.SubElement(root, 'Entity', EntityId=target, EntityClass=cls, Pos='101,200,300', EditorLayer='Trosky')
            props = E.SubElement(node, 'Properties')
            if cls == 'RuntimePrefab': props.set('guidPrefabTemplate', f'native-{kind}-{index}')
            if cls == 'KettleActionTrigger': E.SubElement(props, 'Hold', sAction='BehaviorPoisoningBoiler')
            E.SubElement(links, 'Link', TargetId=target, Name=name)
            back = E.SubElement(node, 'EntityLinks')
            E.SubElement(back, 'Link', TargetId=key, Name='')
        E.SubElement(links, 'Link', TargetId='999999', Name='_eating|,23:00')
    return E.tostring(root)


class CookingTests(unittest.TestCase):
    def build(self):
        files = {'objects_mission0.xml': b'<Objects><Entity EntityId="42" Name="keep"/>'
                 b'<Entity Name="glue_item_5"/><Entity Name="glue_item_7"/></Objects>',
                 'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'}
        with archive({'objects_mission0.xml': source_world()}) as source, archive({'objects_mission0.xml': native_world()}) as native:
            return convert(files, source, native, guid)

    def test_native_effects_and_actions_remain_linked_without_trosky_dependencies(self):
        files, report = self.build()
        nodes = list(E.fromstring(files['objects_mission0.xml']).iter('Entity'))
        generated = [e for e in nodes if e.get('Name', '').startswith('gm_cooking_')]
        ids = {e.get('EntityId'): e.get('EntityGuid') for e in generated}
        self.assertEqual(len(generated), 7)
        for node in generated:
            self.assertNotIn('EditorLayer', node.attrib)
            for link in node.findall('EntityLinks/Link'):
                self.assertEqual(ids[link.get('TargetId')], link.get('TargetGuid'))
        effects = [e.find('Properties').get('guidPrefabTemplate') for e in generated if e.get('EntityClass') == 'RuntimePrefab']
        self.assertEqual(set(effects), {'native-camp-4', 'native-camp-5', 'native-camp-6'})
        network = E.fromstring(files['waitinglinks.xml'])
        for link in network.iter('WaitingLink'):
            self.assertIn(link.get('SourceId'), ids.values())
            self.assertIn(link.get('TargetId'), ids.values())
        self.assertIn('forceFireplaceOn', [n.text for n in network.iter('LinkDefinition')])
        self.assertEqual(report['converted'], 1)

    def test_source_anchors_and_native_item_consumption(self):
        files, _ = self.build()
        nodes = list(E.fromstring(files['objects_mission0.xml']).iter('Entity'))
        kettle = next(e for e in nodes if e.get('EntityClass') == 'KettleActionTrigger')
        self.assertEqual(kettle.get('Pos'), '10,21,31')
        self.assertEqual(kettle.find('Properties/Hold').get('sAction'), 'BehaviorPoisoningBoiler')
        self.assertEqual(kettle.find('Properties/Hold').get('InventoryFilter'), 'poison.*.*|food.*.apple|potion.*.*')
        # Only the source ladle is replaced; the linked household bowl remains.
        self.assertNotIn('glue_item_5', [e.get('Name') for e in nodes])
        self.assertIn('glue_item_7', [e.get('Name') for e in nodes])

    def test_camp_fire_keeps_its_source_origin_below_the_hanging_pot(self):
        files, report = self.build()
        nodes = list(E.fromstring(files['objects_mission0.xml']).iter('Entity'))
        fire = next(e for e in nodes if e.get('Name') == 'gm_cooking_2_' + str(int(DONORS['camp']) + 4))
        self.assertEqual(fire.get('Pos'), '10,20,30.1')
        self.assertEqual(report['fires_rested_on_pot_surface'], 0)
        self.assertEqual(report['records'][0]['fire_lowered_m'], 0.0)
        # No authored st_fire trigger: the native cook trigger stays donor-relative.
        self.assertEqual(report['records'][0]['pan_anchor'], 'donor_relative')
        self.assertEqual(report['pan_triggers_at_source_fire_trigger'], 0)
        pan = next(e for e in nodes if e.get('Name') == 'gm_cooking_2_' + str(int(DONORS['camp']) + 2))
        self.assertEqual(pan.get('EntityClass'), 'FoodProcessingTrigger')
        self.assertNotEqual(pan.get('Pos'), '10,21,31')

    def test_inset_hearth_fire_rests_on_the_pot_surface(self):
        files = {'objects_mission0.xml': b'<Objects/>', 'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'}
        with archive({'objects_mission0.xml': inset_hearth()}) as source, archive({'objects_mission0.xml': native_world()}) as native:
            files, report = convert(files, source, native, guid)
        nodes = list(E.fromstring(files['objects_mission0.xml']).iter('Entity'))
        fire = next(e for e in nodes if e.get('Name') == 'gm_cooking_2_' + str(int(DONORS['home']) + 4))
        x, y, z = map(float, fire.get('Pos').split(','))
        # The flame origin's x/y are kept; the log pile base drops to the pot's resting height.
        self.assertAlmostEqual(x, 821.21039, places=5)
        self.assertAlmostEqual(y, 3487.7664, places=5)
        self.assertAlmostEqual(z, 52.088318, places=5)
        self.assertEqual(report['fires_rested_on_pot_surface'], 1)
        self.assertAlmostEqual(report['records'][0]['fire_lowered_m'], 0.110824, places=5)
        # The native cook-on-fire trigger stands on the authored st_fire trigger, donor yaw kept.
        pan = next(e for e in nodes if e.get('Name') == 'gm_cooking_2_' + str(int(DONORS['home']) + 2))
        self.assertEqual(pan.get('EntityClass'), 'FoodProcessingTrigger')
        for axis, expected in zip(map(float, pan.get('Pos').split(',')), (821.30389, 3486.9893, 52.046768)):
            self.assertAlmostEqual(axis, expected, places=5)
        self.assertNotEqual(pan.get('Rotate'), '0.99144495,0,0,0.13052586')
        self.assertEqual(report['records'][0]['pan_anchor'], 'source_fire_trigger')
        self.assertEqual(report['pan_triggers_at_source_fire_trigger'], 1)
        # The ladle slot filter is unchanged: the Naberacka item stays a visual (not this fix).
        self.assertEqual(report['replaced_ladle_visuals'], 0)

    def test_fire_pivot_never_raises_and_ignores_sub_centimetre_floats(self):
        self.assertEqual(fire_pivot((1.0, 2.0, 30.1), 31.0), (1.0, 2.0, 30.1))
        self.assertEqual(fire_pivot((1.0, 2.0, 31.005), 31.0), (1.0, 2.0, 31.005))
        self.assertEqual(fire_pivot((1.0, 2.0, 31.2), 31.0), (1.0, 2.0, 31.0))

    def test_inactive_quest_layers_are_reported_not_spawned(self):
        layer = source_world().replace(b'EntityId="2"', b'Layer="camp_state1{guid}" EntityId="2"')
        with archive({'layers/camp.xml': layer}) as source:
            _, pots, deferred = inventory(source)
        self.assertEqual(pots, [])
        self.assertEqual(deferred[0]['source_id'], '2')

    def test_reinstall_refuses_duplicate_runtime_entities(self):
        files, _ = self.build()
        with archive({'objects_mission0.xml': source_world()}) as source, archive({'objects_mission0.xml': native_world()}) as native:
            with self.assertRaisesRegex(ValueError, 'already installed'):
                convert(files, source, native, guid)

    def test_missing_owner_fails_instead_of_silently_disabling_pot(self):
        broken = source_world().replace(b'<Link TargetId="1"/>', b'<Link TargetId="999"/>')
        with archive({'objects_mission0.xml': broken}) as source:
            with self.assertRaisesRegex(ValueError, 'expected one fireplace owner'):
                inventory(source)


if __name__ == '__main__': unittest.main()
