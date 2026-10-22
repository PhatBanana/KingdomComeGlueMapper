import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_entity_links import guid_value, native_guid
from campaign_quest_start_placement import apply, load, report, resolve
from setup_quest_starts import upgrade, validate, RECORD


def source_entities():
    return list(E.fromstring('''<Objects>
<Entity Name="different_quest" EntityId="101" EntityGuid="11">
 <EntityLinks>
  <Link Name="QuestActor[('teacher')]" TargetId="102" TargetGuid="0"/>
  <Link Name="QuestPlace[('intro')],OtherTag" TargetId="103"/>
  <Link Name="QuestPlace[('arena')]" TargetId="104"/>
 </EntityLinks>
</Entity>
<Entity Name="another_teacher" EntityId="102" EntityGuid="22" EntityClass="NPC" Pos="300,400,50"/>
<Entity Name="marker" EntityId="103" EntityGuid="33" EntityClass="TagPoint" Pos="5,6,7" Rotate="0,0,0,1"/>
<Entity Name="later_arena" EntityId="104" EntityGuid="44" EntityClass="TagPoint" Pos="100,200,30"/>
</Objects>'''))


def record():
    return resolve(None, source_entities(), 'different_quest', 'teacher', 'intro')


def mission():
    r = record()
    root = E.Element('Objects')
    npc = E.SubElement(root, 'Entity', Name=r['person'], EntityGuid=r['actor_guid'],
                       EntityClass='NPC', EntityId='10', **r['original'])
    E.SubElement(npc, 'Properties', retained='true')
    guid = str(guid_value(r['actor_guid']))
    idle_guid = native_guid(int.from_bytes(hashlib.sha256(('person-idle/'+guid).encode()).digest()[:8], 'little'))
    E.SubElement(root, 'Entity', Name='gm_person_idle_'+r['person'], EntityGuid=idle_guid,
                 EntityClass='TagPoint', EntityId='11', **r['original'])
    E.SubElement(root, 'Entity', Name='authored_work_target', EntityGuid=native_guid(99), Pos='100,200,30')
    return E.tostring(root)


class QuestStartPlacementTests(unittest.TestCase):
    def test_resolves_roles_without_names_or_coordinates_in_converter(self):
        entities = source_entities()
        before = [E.tostring(e) for e in entities]
        r = resolve(None, entities, 'different_quest', 'teacher', 'intro')
        self.assertEqual(r['person'], 'another_teacher')
        self.assertEqual(r['placement'], {'Pos':'5,6,7', 'Rotate':'0,0,0,1'})
        self.assertEqual([E.tostring(e) for e in entities], before)
        self.assertFalse(report([r])['controller_converted'])

    def test_parent_local_marker_is_composed_into_world_space(self):
        entities = source_entities()
        entities[2].set('ParentId', '104')
        r = resolve(None, entities, 'different_quest', 'teacher', 'intro')
        self.assertEqual(r['placement']['Pos'], '105,206,37')

    def test_missing_ambiguous_and_disagreeing_links_fail(self):
        for mode in ('missing', 'ambiguous', 'guid'):
            entities = source_entities()
            links = entities[0].find('EntityLinks')
            if mode == 'missing': links.remove(links[0])
            if mode == 'ambiguous': links.append(copy.deepcopy(links[0]))
            if mode == 'guid': links[0].set('TargetGuid', '99')
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                resolve(None, entities, 'different_quest', 'teacher', 'intro')

    def test_repair_existing_actor_and_idle_anchor_preserves_other_content(self):
        original = mission()
        updated, changes = apply(original, [record()])
        root = E.fromstring(updated)
        self.assertEqual(changes, ['another_teacher', 'gm_person_idle_another_teacher'])
        self.assertEqual(root[0].get('Pos'), '5,6,7')
        self.assertEqual(root[1].get('Pos'), '5,6,7')
        self.assertEqual(root[2].get('Pos'), '100,200,30')
        self.assertEqual(root[0].find('Properties').get('retained'), 'true')
        again, changes = apply(updated, [record()])
        self.assertEqual((again, changes), (updated, []))

    def test_fresh_actor_with_correct_pose_but_stale_anchor_is_repaired(self):
        root = E.fromstring(mission())
        root[0].attrib.update(record()['placement'])
        updated, changes = apply(E.tostring(root), [record()])
        self.assertEqual(changes, ['gm_person_idle_another_teacher'])
        self.assertEqual(E.fromstring(updated)[1].get('Pos'), '5,6,7')

    def test_custom_pose_or_wrong_anchor_identity_is_not_reset(self):
        for mode in ('actor', 'anchor', 'identity'):
            root = E.fromstring(mission())
            if mode == 'identity': root[1].set('Name', 'different_owner')
            else: root[0 if mode == 'actor' else 1].set('Pos', '500,500,50')
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                apply(E.tostring(root), [record()])

    def test_duplicate_source_copies_and_cross_layer_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pak = root/'Data/Levels/test/level.pak'
            pak.parent.mkdir(parents=True)
            entities = source_entities()
            with zipfile.ZipFile(pak, 'w') as z:
                z.writestr('objects_mission0.xml', b'<Objects>'+E.tostring(entities[0])+b'</Objects>')
                z.writestr('Layers/source.xml', b'<Objects>'+b''.join(map(E.tostring, entities))+b'</Objects>')
            self.assertEqual(load(root, 'test', [('different_quest','teacher','intro')]), [record()])
            with self.assertRaisesRegex(ValueError, 'Multiple quest starting'):
                load(root, 'test', [('different_quest','teacher','intro')]*2)

    def test_resume_updates_only_mission_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pak = root/'Data/Levels/kcd1_travel/level.pak'
            pak.parent.mkdir(parents=True)
            with zipfile.ZipFile(pak, 'w') as z:
                z.writestr('objects_mission0.xml', mission())
                z.writestr('tables/ai/scheduler.xml', b'unchanged schedules')
                z.writestr('terrain/terrain.dat', b'unchanged terrain')
            with patch('setup_quest_starts.plans', return_value=[record()]):
                baseline=root/'baseline-record.json'
                baseline.write_bytes(b'baseline metadata')
                (root/RECORD).hardlink_to(baseline)
                files, evidence = upgrade(root, Path('source'))
                self.assertEqual(baseline.read_bytes(),b'baseline metadata')
                before = pak.read_bytes()
                again, _ = upgrade(root, Path('source'))
            self.assertEqual(before, pak.read_bytes())
            self.assertEqual(files, again)
            self.assertEqual(json.loads((root/RECORD).read_text()), evidence)
            with zipfile.ZipFile(pak) as z:
                self.assertEqual(z.read('tables/ai/scheduler.xml'), b'unchanged schedules')
                self.assertEqual(z.read('terrain/terrain.dat'), b'unchanged terrain')
                with patch('setup_quest_starts.SELECTIONS', (('different_quest','teacher','intro'),)):
                    validate(z.read('objects_mission0.xml'), evidence)
                    with self.assertRaisesRegex(ValueError, 'base world'):
                        validate(mission(), evidence)

    def test_clean_setup_passes_source_pose_and_repairs_reused_actor(self):
        from setup_gameplay import actors
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); output = root/'stage'
                def build(args):
                    self.assertEqual(args.placements, {'another_teacher': record()['placement']})
                    level = args.output/'package/Data/Levels/kcd1_travel/level.pak'
                    level.parent.mkdir(parents=True)
                    data = mission()
                    if not existing:
                        data, _ = apply(data, [record()])
                    with zipfile.ZipFile(level, 'w') as z:
                        z.writestr('objects_mission0.xml', data)
                        z.writestr('other', b'preserve')
                    (args.output/'report.json').write_text(json.dumps(dict(pending=[],
                        existing=[{'person':'another_teacher'}] if existing else [],
                        converted=[] if existing else [{'person':'another_teacher'}])))
                with patch('setup_gameplay.PEOPLE', ('another_teacher',)), patch(
                        'setup_gameplay.SCENE_PEOPLE', {}), patch(
                        'setup_quest_starts.plans', return_value=[record()]), patch(
                        'campaign_scene_test.source_scene_positions', return_value={}), patch(
                        'build_quest_people_test.build', side_effect=build):
                    actors(root/'source', root/'target', root/'base', output)
                with zipfile.ZipFile(output/'package/Data/Levels/kcd1_travel/level.pak') as z:
                    self.assertEqual(apply(z.read('objects_mission0.xml'), [record()])[1], [])
                    self.assertEqual(z.read('other'), b'preserve')
                self.assertEqual(json.loads((output/'package'/RECORD).read_text()), report([record()]))


if __name__ == '__main__':
    unittest.main()
