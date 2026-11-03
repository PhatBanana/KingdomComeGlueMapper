from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from hearth_fire_placement import LEVEL, SOURCE_LEVEL, VERSION, plan, stage, upgrade


@contextmanager
def archive(files):
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
        path = Path(directory) / 'fixture.pak'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in files.items():
                z.writestr(name, data)
        with zipfile.ZipFile(path) as z:
            yield z


# An inset (black kitchen) hearth with pot, cook trigger, flame and pot item, and a
# camp fire whose cook trigger sits under the hanging pot.
SOURCE = b'''<Objects>
  <Entity EntityId="1" EntityClass="SmartObjectHolder" Pos="820.8,3487.6,52.28" Rotate="0.6756,0,0,-0.7373">
    <Properties soclasses_SmartObjectHelpers="Fireplace_CernaKuchyn"/>
    <EntityLinks><Link Name="st_kettle" TargetId="2"/><Link Name="st_fire" TargetId="10"/>
    <Link Name="fireProcedural[('fireplace_inset')]" TargetId="3"/><Link TargetId="8"/></EntityLinks></Entity>
  <Entity EntityId="2" EntityClass="SequenceTrigger" Pos="821.2074,3487.3896,52.046768">
    <Properties><Click UseMessage="@ui_eat_kettle"/></Properties><EntityLinks><Link TargetId="1"/></EntityLinks></Entity>
  <Entity EntityId="10" EntityClass="SequenceTrigger" Pos="821.30389,3486.9893,52.046768" Rotate="0.99144495,0,0,0.13052586">
    <Properties><Click UseMessage="@ui_cook_item"/></Properties><EntityLinks><Link TargetId="1"/></EntityLinks></Entity>
  <Entity EntityId="3" EntityClass="ProceduralObject" Pos="821.21039,3487.7664,52.199142" Rotate="0.3535535,-0.35355353,-0.61237234,0.6123724"/>
  <Entity EntityId="8" EntityClass="PickableItem" Pos="821.22852,3487.3599,52.088318"><Properties sWH_AI_EntityCategory="Kotlik"/></Entity>
  <Entity EntityId="11" EntityClass="SmartObjectHolder" Pos="10,20,30">
    <Properties soclasses_SmartObjectHelpers="Fireplace_camp"/>
    <EntityLinks><Link Name="st_kettle" TargetId="12"/><Link Name="st_fire" TargetId="14"/>
    <Link Name="fireProcedural['fire_medium']" TargetId="13"/></EntityLinks></Entity>
  <Entity EntityId="12" EntityClass="SequenceTrigger" Pos="10,20,30.2">
    <Properties><Click UseMessage="@ui_eat_kettle"/></Properties><EntityLinks><Link TargetId="11"/></EntityLinks></Entity>
  <Entity EntityId="14" EntityClass="SequenceTrigger" Pos="10.01,20.01,30.02"><Properties><Click UseMessage="@ui_cook_item"/></Properties></Entity>
  <Entity EntityId="13" EntityClass="ProceduralObject" Pos="10,20,30"/>
</Objects>'''


def mission(fire_z='52.199142', include_camp=True, fire_link=True, pan_pos='820.43,3487.2,53.16', camp_pan_pos='10.6,20.4,30.3'):
    root = E.Element('Objects')
    home = E.SubElement(root, 'Entity', EntityId='100', EntityClass='FireplaceSmartObject', Name='gm_cooking_2_24041', Pos='820.8,3487.6,52.28')
    links = E.SubElement(home, 'EntityLinks')
    if fire_link:
        E.SubElement(links, 'Link', Name="proceduralObject['fire']", TargetId='101')
    E.SubElement(links, 'Link', Name="kettleTrigger['pan']", TargetId='102')
    E.SubElement(links, 'Link', Name='forceFireplaceOn', TargetId='100')
    E.SubElement(root, 'Entity', EntityId='101', EntityClass='RuntimePrefab', Name='gm_cooking_2_24043', Pos='821.21039,3487.7664,' + fire_z)
    E.SubElement(root, 'Entity', EntityId='102', EntityClass='FoodProcessingTrigger', Name='gm_cooking_2_24046', Pos=pan_pos, Rotate='0.1564,0,0,-0.9877')
    if include_camp:
        camp = E.SubElement(root, 'Entity', EntityId='200', EntityClass='FireplaceSmartObject', Name='gm_cooking_12_16229', Pos='10,20,30')
        camp_links = E.SubElement(camp, 'EntityLinks')
        E.SubElement(camp_links, 'Link', Name="proceduralObject['fire']", TargetId='201')
        E.SubElement(camp_links, 'Link', Name="kettleTrigger['pan']", TargetId='202')
        E.SubElement(root, 'Entity', EntityId='201', EntityClass='RuntimePrefab', Name='gm_cooking_12_16230', Pos='10,20,30')
        E.SubElement(root, 'Entity', EntityId='202', EntityClass='FoodProcessingTrigger', Name='gm_cooking_12_16226', Pos=camp_pan_pos)
    E.SubElement(root, 'Entity', EntityId='300', EntityClass='Stash', Name='gm_container_7', Pos='1,2,3')
    return E.tostring(root)


def positions(blob):
    return {e.get('Name'): e.get('Pos') for e in E.fromstring(blob).iter('Entity')}


def xyz(text):
    return tuple(map(float, text.split(',')))


class HearthFirePlacementTests(unittest.TestCase):
    def test_fire_rests_on_the_pot_surface_and_cook_triggers_stand_on_the_source_fire_trigger(self):
        with archive({'objects_mission0.xml': SOURCE}) as source:
            updated, report = plan(mission(), source)
        self.assertIsNotNone(updated)
        after = positions(updated)
        fire = xyz(after['gm_cooking_2_24043'])
        self.assertAlmostEqual(fire[0], 821.21039, places=5)
        self.assertAlmostEqual(fire[1], 3487.7664, places=5)
        self.assertAlmostEqual(fire[2], 52.088318, places=5)
        for axis, expected in zip(xyz(after['gm_cooking_2_24046']), (821.30389, 3486.9893, 52.046768)):
            self.assertAlmostEqual(axis, expected, places=5)
        for axis, expected in zip(xyz(after['gm_cooking_12_16226']), (10.01, 20.01, 30.02)):
            self.assertAlmostEqual(axis, expected, places=5)
        self.assertEqual(after['gm_cooking_12_16230'], '10,20,30')  # camp flame below its hanging pot
        self.assertEqual(after['gm_container_7'], '1,2,3')
        # Rotations are untouched: KCD1 triggers are omnidirectional, the donor yaw stays.
        rotations = {e.get('Name'): e.get('Rotate') for e in E.fromstring(updated).iter('Entity')}
        self.assertEqual(rotations['gm_cooking_2_24046'], '0.1564,0,0,-0.9877')
        self.assertEqual(report['version'], VERSION)
        self.assertEqual(report['fireplaces'], 2)
        self.assertEqual(report['moved_by_role'], {'fire': 1, 'pan': 2})
        self.assertEqual(report['unchanged'], 1)
        self.assertEqual(report['skipped'], [])
        self.assertFalse(report['runtime_verified'])
        by_entity = {m['entity']: m for m in report['moved']}
        fire_move = by_entity['gm_cooking_2_24043']
        self.assertEqual((fire_move['role'], fire_move['fireplace'], fire_move['kind']), ('fire', 'gm_cooking_2_24041', 'home'))
        self.assertEqual((fire_move['source_pot'], fire_move['source_fireplace']), ('2', '1'))
        self.assertAlmostEqual(fire_move['before'][2], 52.199142, places=5)
        self.assertAlmostEqual(fire_move['lowered_m'], 0.110824, places=5)
        pan_move = by_entity['gm_cooking_2_24046']
        self.assertEqual(pan_move['role'], 'pan')
        self.assertAlmostEqual(pan_move['lowered_m'], 53.16 - 52.046768, places=5)

    def test_second_pass_changes_nothing(self):
        with archive({'objects_mission0.xml': SOURCE}) as source:
            updated, _ = plan(mission(), source)
            again, report = plan(updated, source)
        self.assertIsNone(again)
        self.assertEqual(report['moved'], [])
        self.assertEqual(report['unchanged'], 4)

    def test_displaced_fire_is_normalised_to_the_rule_not_to_its_current_height(self):
        # The step derives the canonical pivot from the KCD1 origin and the pot;
        # a package whose fire drifted below that height is brought back to it.
        with archive({'objects_mission0.xml': SOURCE}) as source:
            updated, report = plan(mission(fire_z='51.9'), source)
        self.assertAlmostEqual(xyz(positions(updated)['gm_cooking_2_24043'])[2], 52.088318, places=5)
        fire_move = next(m for m in report['moved'] if m['role'] == 'fire')
        self.assertAlmostEqual(fire_move['lowered_m'], -0.188318, places=5)

    def test_hearth_without_a_source_fire_trigger_keeps_the_donor_cook_trigger(self):
        without = SOURCE.replace(b'<Link Name="st_fire" TargetId="10"/>', b'').replace(b'<Link Name="st_fire" TargetId="14"/>', b'')
        with archive({'objects_mission0.xml': without}) as source:
            updated, report = plan(mission(fire_z='52.088318'), source)
        self.assertIsNone(updated)
        self.assertEqual(report['moved_by_role'], {'fire': 0, 'pan': 0})
        self.assertEqual(report['unchanged'], 4)

    def test_unconverted_pot_is_reported_and_missing_links_fail(self):
        with archive({'objects_mission0.xml': SOURCE}) as source:
            _, report = plan(mission(include_camp=False), source)
            self.assertEqual(report['skipped'], [{'source_pot': '12', 'reason': 'not converted'}])
            with self.assertRaisesRegex(ValueError, "no proceduralObject\\['fire'\\] link"):
                plan(mission(fire_link=False), source)

    def test_stage_writes_a_copy_and_upgrade_rewrites_the_package(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            (root / 'mod' / Path(LEVEL).parent).mkdir(parents=True)
            with zipfile.ZipFile(root / 'mod' / LEVEL, 'w') as z:
                z.writestr('objects_mission0.xml', mission())
                z.writestr('other.xml', b'<keep/>')
            (root / 'source' / Path(SOURCE_LEVEL).parent).mkdir(parents=True)
            with zipfile.ZipFile(root / 'source' / SOURCE_LEVEL, 'w') as z:
                z.writestr('objects_mission0.xml', SOURCE)
            report = stage(root / 'mod', root / 'source', root / 'out')
            self.assertEqual(report['changed_entries'], ['objects_mission0.xml'])
            saved = json.loads((root / 'out' / 'report.json').read_text())
            self.assertEqual(saved['moved_by_role'], {'fire': 1, 'pan': 2})
            with zipfile.ZipFile(root / 'out' / LEVEL) as z:
                self.assertEqual(z.read('other.xml'), b'<keep/>')
                staged = positions(z.read('objects_mission0.xml'))
            self.assertAlmostEqual(xyz(staged['gm_cooking_2_24043'])[2], 52.088318, places=5)
            with zipfile.ZipFile(root / 'mod' / LEVEL) as z:
                self.assertEqual(positions(z.read('objects_mission0.xml'))['gm_cooking_2_24043'].split(',')[2], '52.199142')
            with self.assertRaises(FileExistsError):
                stage(root / 'mod', root / 'source', root / 'out')
            files, report = upgrade(root / 'mod', root / 'source')
            self.assertEqual(set(files), {LEVEL})
            self.assertEqual(report['changed_entries'], ['objects_mission0.xml'])
            with zipfile.ZipFile(root / 'mod' / LEVEL) as z:
                self.assertIsNone(z.testzip())
                self.assertAlmostEqual(xyz(positions(z.read('objects_mission0.xml'))['gm_cooking_2_24043'])[2], 52.088318, places=5)
            files, report = upgrade(root / 'mod', root / 'source')
            self.assertEqual(report['changed_entries'], [])
            self.assertEqual(report['moved'], [])
            self.assertEqual(set(files), {LEVEL})


if __name__ == '__main__':
    unittest.main()
