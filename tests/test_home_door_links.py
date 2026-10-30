from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_entity_links import native_guid
from home_door_links import (convert, door_kind, privacy_label, script_values, source_areas, stage, upgrade,
                             DEFINITION, LEVEL)

AREA = 0xABC0000000000123
DOOR_GUIDS = {sid: native_guid(0x5000 + sid) for sid in (11, 12, 13, 14)}


def door(mission, sid, locked='0', passing='1', lock_types='manual/key'):
    e = E.SubElement(mission, 'Entity', Name='gm_door_%d' % sid, EntityClass='AnimDoor', EntityId=str(100 + sid),
                     EntityGuid=DOOR_GUIDS[sid], Pos='1,2,3')
    props = E.SubElement(e, 'Properties', object_Model='doors/x.cdf')
    E.SubElement(props, 'Lock', bLocked=locked, esLockTypes=lock_types, bNeverLockByPassingNPC=passing,
                 fKeepUnlockedFrom='7.5', fKeepUnlockedTo='19.5', bDoLockOnMissingHomeArea='0')
    return e


def mission(label=None):
    root = E.Element('Objects')
    npc = E.SubElement(root, 'Entity', Name='villager', EntityClass='NPC', EntityId='1', EntityGuid=native_guid(1), Pos='0,0,0')
    hub = E.SubElement(root, 'Entity', Name='gm_person_home_villager', EntityClass='SchedulerHub', EntityId='2', EntityGuid=native_guid(2), Pos='0,0,0')
    area = E.SubElement(root, 'Entity', Name='Ska_SA_Home9', EntityClass='TriggerArea', EntityId='3', EntityGuid=native_guid(AREA), Pos='0,0,0')
    props = E.SubElement(area, 'Properties', bSaved_by_game='0')
    if label is not None: props.set('Label', label)
    E.SubElement(E.SubElement(npc, 'EntityLinks'), 'Link', Name='home', TargetId='2', TargetGuid=native_guid(2))
    E.SubElement(E.SubElement(hub, 'EntityLinks'), 'Link', Name='home_area', TargetId='3', TargetGuid=native_guid(AREA))
    for sid in (11, 12, 13, 14): door(root, sid)
    E.SubElement(root, 'Entity', Name='glue_item_16', EntityClass='Stash', EntityId='116', EntityGuid=native_guid(0x6016), Pos='0,0,0')
    return root


def source_area(misc='', links=None):
    area = E.Element('Entity', Name='Ska_SA_Home9', EntityClass='SmartAreaShape', EntityId='900', EntityGuid='%016X' % AREA, Pos='0,0,0')
    props = E.SubElement(area, 'Properties', guidSmartAreaTemplate='5fdc7a5e-0b61-43fe-bc6a-53423136d493')
    E.SubElement(props, 'Script', Misc=misc, bValidWithoutTemplate='0')
    container = E.SubElement(area, 'EntityLinks')
    for name, target in (links if links is not None else
                         [('entrance', '11'), ('stash_door', '12'), ('', '13'), ('sleepoverDoor', '14'), ('entrance', '15'), ('', '16'), ('', '17')]):
        E.SubElement(container, 'Link', Name=name, TargetId=target, TargetGuid='0')
    return area


def files(root):
    return {'objects_mission0.xml': E.tostring(root), 'waitinglinks.xml': None}


def links_of(data, area_id='3'):
    area = next(e for e in E.fromstring(data['objects_mission0.xml']).iter('Entity') if e.get('EntityId') == area_id)
    return area, {(l.get('Name'), l.get('TargetId')) for l in area.findall('EntityLinks/Link')}


class HomeDoorLinkTests(unittest.TestCase):
    def test_source_links_become_native_crime_doors_with_personal_label(self):
        areas = {native_guid(AREA): [source_area()]}
        result, report = convert(files(mission()), areas, source_doors={'15', '17'})
        area, links = links_of(result)
        self.assertEqual(area.find('Properties').get('Label'), 'private;personal')
        self.assertEqual(links, {(DEFINITION % 'entrance', '111'), (DEFINITION % 'storage', '112'), (DEFINITION % 'basic', '113')})
        waiting = E.fromstring(result['waitinglinks.xml'])
        definitions = {(w.get('SourceId'), w.get('TargetId'), w.findtext('LinkDefinition')) for w in waiting.iter('WaitingLink')}
        self.assertEqual(definitions, {(native_guid(AREA), DOOR_GUIDS[sid], DEFINITION % kind)
                                       for sid, kind in ((11, 'entrance'), (12, 'storage'), (13, 'basic'))})
        locks = {e.get('Name'): e.find('Properties/Lock') for e in E.fromstring(result['objects_mission0.xml']).iter('Entity') if e.get('EntityClass') == 'AnimDoor'}
        self.assertEqual([locks['gm_door_%d' % s].get('bNeverLockByPassingNPC') for s in (11, 12, 13)], ['0', '0', '0'])
        self.assertEqual(locks['gm_door_14'].get('bNeverLockByPassingNPC'), '1')
        self.assertEqual(locks['gm_door_11'].get('bDoLockOnMissingHomeArea'), '0')
        self.assertEqual(locks['gm_door_11'].get('fKeepUnlockedFrom'), '7.5')
        home, = report['homes']
        self.assertEqual(home['status'], 'converted')
        self.assertEqual([d['kind'] for d in home['doors']], ['basic', 'entrance', 'storage'])  # source links sorted by name
        self.assertEqual(home['skipped'], [dict(link='sleepoverDoor', door='gm_door_14')])
        # 15 is an unconverted entrance door, 17 an unconverted source door; 16 is not a door at all.
        self.assertEqual([(p['link'], p['source_id']) for p in home['pending']], [('', '17'), ('entrance', '15')])
        self.assertEqual((report['doors'], report['pending'], report['skipped'], report['labels']), (3, 2, 1, {'private;personal': 1}))
        self.assertFalse(report['runtime_verified'])

    def test_nonprivate_home_links_doors_without_a_privacy_label(self):
        areas = {native_guid(AREA): [source_area('nonprivateHome:true')]}
        result, report = convert(files(mission()), areas)
        area, links = links_of(result)
        self.assertIsNone(area.find('Properties').get('Label'))
        self.assertEqual(len(links), 3)
        self.assertEqual(report['labels'], {'none': 1})

    def test_repeat_application_is_identical(self):
        areas = {native_guid(AREA): [source_area()]}
        once, report = convert(files(mission()), areas)
        twice, repeat = convert(once, areas)
        self.assertEqual(once['objects_mission0.xml'], twice['objects_mission0.xml'])
        self.assertEqual(once['waitinglinks.xml'], twice['waitinglinks.xml'])
        self.assertEqual(report, repeat)

    def test_disagreeing_quest_state_variants_are_reported_not_guessed(self):
        areas = {native_guid(AREA): [source_area(), source_area(links=[('entrance', '12')])]}
        result, report = convert(files(mission()), areas)
        self.assertEqual(report['homes'][0]['status'], 'ambiguous_source_variants')
        self.assertIsNone(result['waitinglinks.xml'])
        _, links = links_of(result)
        self.assertEqual(links, set())

    def test_home_without_source_area_and_conflicting_label_are_handled(self):
        result, report = convert(files(mission()), {})
        self.assertEqual(report['homes'][0]['status'], 'no_source_area')
        self.assertEqual(result['objects_mission0.xml'], files(mission())['objects_mission0.xml'])
        with self.assertRaisesRegex(ValueError, 'different label'):
            convert(files(mission(label='music_gm_cave_positive')), {native_guid(AREA): [source_area()]})
        with self.assertRaisesRegex(ValueError, 'trespass level'):
            convert(files(mission()), {native_guid(AREA): [source_area('trespass:weird')]})

    def test_source_policy_and_link_name_mapping(self):
        self.assertEqual(door_kind('entrance'), 'entrance')
        self.assertEqual(door_kind('stash_door,entrance'), 'entrance')
        self.assertEqual(door_kind("QuestPlace[('doorOuter')],entrance"), 'entrance')
        self.assertEqual(door_kind('stash_door'), 'storage')
        self.assertEqual(door_kind(''), 'basic')
        self.assertIsNone(door_kind('sleepoverDoorNeverLock'))
        self.assertIsNone(door_kind('unlockAfterCrime'))
        self.assertEqual(script_values('nonprivateHome:true'), {'nonprivateHome': 'true'})
        self.assertEqual(script_values('trespass:none;pubType:semiRoof'), {'trespass': 'none', 'pubType': 'semiRoof'})
        self.assertEqual(privacy_label(''), 'private;personal')
        self.assertEqual(privacy_label('notFullyEquiped:true'), 'private;personal')
        self.assertIsNone(privacy_label('nonprivateHome:true'))
        self.assertIsNone(privacy_label('trespass:none'))
        self.assertEqual(privacy_label('trespass:prohibited'), 'private;prohibited')
        self.assertEqual(privacy_label('trespassMode:nightOnly'), 'private;semipublic')
        with self.assertRaises(ValueError): privacy_label('trespassMode:sometimes')

    def test_stage_and_upgrade_rewrite_the_level_archive_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp)/'mod'; source = Path(tmp)/'kcd1'
            (mod/'Data/Levels/kcd1_travel').mkdir(parents=True); (source/'Data/Levels/rataje').mkdir(parents=True)
            with zipfile.ZipFile(mod/LEVEL, 'w') as z:
                z.writestr('objects_mission0.xml', E.tostring(mission()))
                z.writestr('other.bin', b'keep')
            layer = E.Element('Objects'); layer.append(source_area())
            E.SubElement(layer, 'Entity', Name='door15', EntityClass='AnimDoor', EntityId='15', EntityGuid='%016X' % 0x15)
            with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak', 'w') as z:
                z.writestr('layers/home9{x}.xml', E.tostring(layer))
                z.writestr('objects_mission0.xml', b'<Objects />')
            areas, doors = source_areas(source)
            self.assertEqual((set(areas), doors), ({native_guid(AREA)}, {'15'}))
            changed, report = upgrade(mod, source)
            self.assertEqual(set(changed), {LEVEL})
            self.assertEqual(report['changed_entries'], ['objects_mission0.xml', 'waitinglinks.xml'])
            self.assertEqual([(p['link'], p['source_id']) for p in report['homes'][0]['pending']], [('entrance', '15')])
            with zipfile.ZipFile(mod/LEVEL) as z:
                self.assertEqual(z.read('other.bin'), b'keep')
                _, links = links_of({'objects_mission0.xml': z.read('objects_mission0.xml')})
                self.assertEqual(len(links), 3)
                self.assertIn(b'crime_doorKind.storage', z.read('waitinglinks.xml'))
            again, repeat = upgrade(mod, source)
            self.assertEqual((again, repeat['changed_entries']), ({}, []))
            self.assertEqual(repeat['homes'], report['homes'])
            with self.assertRaises(FileExistsError):
                stage(mod, source, mod)


if __name__ == '__main__': unittest.main()
