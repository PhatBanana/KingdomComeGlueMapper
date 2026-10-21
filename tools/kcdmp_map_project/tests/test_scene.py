"""Synthetic contract tests; these are not KCD2 runtime tests."""
import io
import math
import struct
import unittest
import xml.etree.ElementTree as ET
import zipfile

from kcdmp_bridge.scene import prepare_scene, transform_level_entry, SPAWN_NAME


def package(mission, **extra):
    stream = io.BytesIO()
    entries = {
        "objects_mission0.xml": mission,
        "mission_mission0.xml": b'<Mission><Environment><EnvState UseLayersActivation="1"/></Environment></Mission>',
        "levelinfo.xml": b'<LevelInfo Name="data/levels/kcd1_travel"/>',
        "leveldata.xml": b'<LevelData><Layers><Layer Name="town_state0" Id="3"/></Layers></LevelData>',
        "whdata_0": b'<Root version="1"><ConceptManager><ConceptPaths><Path>quests/start.xml</Path></ConceptPaths><ConceptModules><Module>start</Module></ConceptModules></ConceptManager><AI><LevelPath>data/levels/kcd1_travel</LevelPath><SmartAreaManager version="2"><SmartAreas><SmartArea><Guid>17</Guid></SmartArea></SmartAreas></SmartAreaManager></AI><SoulList><Souls><Soul><Name>native_player</Name><Player>1</Player><EntityGuid>30583</EntityGuid></Soul><Soul><Name>npc</Name><Player>0</Player></Soul></Souls></SoulList></Root>',
    }
    entries.update(extra)
    with zipfile.ZipFile(stream, "w") as archive:
        for name, contents in entries.items():
            archive.writestr(name, contents)
    stream.seek(0)
    return zipfile.ZipFile(stream)


MARKER = '<Entity Name="gmtravel_arrival_kcd1" EntityClass="TagPoint" EntityId="10" EntityGuid="0000000a-0000-0000" Pos="3831.58,1787.66,127.43" Rotate="0.7071067811865476,0,0,0.7071067811865476"/>'


class SceneTests(unittest.TestCase):
    def test_scenery_and_bake_are_preserved_campaign_is_removed(self):
        objects = ('<Objects>' + MARKER +
                   '<Entity Name="building" EntityClass="GeomEntity" EntityId="11" Geometry="gluebuild/house.cgf" Pos="4,5,6">'
                   '<Properties bSaved_by_game="1"/><FlowGraph><StartQuest/></FlowGraph></Entity>'
                   '<Entity Name="gi" EntityClass="EnvironmentLight" EntityId="12" EntityGuid="0000000c-0000-0000"><Properties bActive="1"/></Entity>'
                   '<Entity Name="quest" EntityClass="Concept" EntityId="13"/>'
                   '<Entity Name="person" EntityClass="NPC" EntityId="14"/>'
                   '<Entity Name="kcd1_travel" EntityClass="LevelHolder" EntityId="15"/>'
                   '<Entity Name="oldstart" EntityClass="SpawnPoint" EntityId="16"/>'
                   '</Objects>')
        baked = b"opaque already-baked SVO, terrain and HLOD payload"
        with package(objects, **{"terrain/hlods.dat": baked}) as archive:
            context = prepare_scene(archive)
            out = ET.fromstring(transform_level_entry("objects_mission0.xml", b"unused", context))
            classes = [x.get("EntityClass") for x in out]
            self.assertEqual(classes.count("SpawnPoint"), 1)
            self.assertNotIn("Concept", classes)
            self.assertNotIn("NPC", classes)
            self.assertNotIn("LevelHolder", classes)
            self.assertIn("EnvironmentLight", classes)
            self.assertIsNone(out.find('.//FlowGraph'))
            self.assertEqual(transform_level_entry("terrain/hlods.dat", baked, context), baked)
            self.assertFalse(context.report["runtime_verified"])
            self.assertAlmostEqual(context.heading, 90)
            self.assertEqual(context.spawn_xyz, (3831.58, 1787.66, 127.43))
            self.assertEqual(out.find(f'Entity[@Name="{SPAWN_NAME}"]').get("Pos"), "3831.58,1787.66,127.43")
            self.assertEqual(ET.fromstring(context.replacements["mission_mission0.xml"]).find("Environment/EnvState").get("UseLayersActivation"), "0")
            world = ET.fromstring(context.replacements["whdata_0"])
            self.assertEqual(len(world.findall("SoulList/Souls/Soul")), 1)
            self.assertEqual(world.findtext("SoulList/Souls/Soul/Name"), "native_player")
            self.assertEqual(world.findtext("ConceptManager/IncludeModGraphs"), "0")
            self.assertEqual(len(world.findall(".//Path")), 0)
            self.assertEqual(len(world.findall(".//SmartArea")), 0)

    def test_inert_furnishings_keep_models_without_gameplay(self):
        objects = ('<Objects>' + MARKER +
                   '<Entity Name="chest" EntityClass="Stash" EntityId="2" Geometry="objects/chest.cgf">'
                   '<Properties guidInventory="bad" fileConcept="quest.xml"/><EntityLinks><Link TargetId="3"/></EntityLinks></Entity>'
                   '<Entity Name="door" EntityClass="AnimDoor" EntityId="3"><Properties object_Model="objects/door.cdf" guidQuest="q"/></Entity>'
                   '<Entity Name="unknown-model" EntityClass="Stash" EntityId="4"><Properties guidInventory="unknown"/></Entity>'
                   '</Objects>')
        with package(objects) as archive:
            context = prepare_scene(archive)
        output = ET.fromstring(context.replacements["objects_mission0.xml"])
        chest = output.find('Entity[@Name="chest"]')
        self.assertEqual(chest.get("EntityClass"), "GeomEntity")
        self.assertEqual(chest.get("Geometry"), "objects/chest.cgf")
        self.assertIsNone(chest.find("EntityLinks"))
        self.assertIsNone(chest.find("Properties").get("guidInventory"))
        door = output.find('Entity[@Name="door"]')
        self.assertEqual(door.get("EntityClass"), "AnimChar")
        self.assertEqual(door.find("Properties").get("object_Model"), "objects/door.cdf")
        self.assertEqual(door.find("Properties/Physics").get("bRigidBody"), "0")
        self.assertIsNone(output.find('Entity[@Name="unknown-model"]'))

    def test_parent_removal_preserves_world_transform(self):
        objects = ('<Objects>' + MARKER +
                   '<Entity Name="controller" EntityClass="NPC" EntityId="4" Pos="100,200,3" Rotate="0.7071067811865476,0,0,0.7071067811865476"/>'
                   '<Entity Name="child" EntityClass="GeomEntity" EntityId="5" ParentId="4" Pos="2,0,1" Geometry="objects/a.cgf"/>'
                   '</Objects>')
        with package(objects) as archive:
            context = prepare_scene(archive)
        child = ET.fromstring(context.replacements["objects_mission0.xml"]).find('Entity[@Name="child"]')
        self.assertEqual(tuple(map(float, child.get("Pos").split(","))), (100, 202, 4))
        self.assertIsNone(child.get("ParentId"))

    def test_preserves_visual_links_prunes_gameplay_targets(self):
        objects = ('<Objects>' + MARKER +
                   '<Entity EntityId="11" EntityGuid="0000000b-0000-0000" Name="light" EntityClass="EnvironmentLight"><EntityLinks>'
                   '<Link Name="clip" TargetId="12" TargetGuid="0000000c-0000-0000"/>'
                   '<Link Name="quest" TargetId="13" TargetGuid="0000000d-0000-0000"/>'
                   '</EntityLinks></Entity>'
                   '<Entity EntityId="12" EntityGuid="0000000c-0000-0000" EntityClass="ClipVolume"/>'
                   '<Entity EntityId="13" EntityGuid="0000000d-0000-0000" EntityClass="Concept"/>'
                   '</Objects>')
        with package(objects) as archive:
            context = prepare_scene(archive)
        links = ET.fromstring(context.replacements["objects_mission0.xml"]).findall('.//EntityLinks/Link')
        self.assertEqual([x.get("Name") for x in links], ["clip"])
        self.assertEqual(context.report["pruned_entity_links"], 1)

    def test_initial_layers_flatten_and_other_layers_are_empty(self):
        initial = b'<Objects><Entity Name="treeprop" EntityClass="GeomEntity" EntityId="44" Layer="town_state0" Pos="5,6,7" Geometry="objects/p.cgf"/></Objects>'
        later = b'<Objects><Entity Name="burningprop" EntityClass="GeomEntity" EntityId="45" Geometry="objects/b.cgf"/></Objects>'
        with package('<Objects>'+MARKER+'</Objects>', **{"layers/town_state0.xml": initial, "layers/town_state1.xml": later,
                "whdata_1": b'<Root><GameProfileManager><GameProfiles><GameProfile><Name>story</Name><Id>0</Id></GameProfile></GameProfiles></GameProfileManager></Root>',
                "extractedlayerentityids.xml": b'<ReservedEntityIDsFromLayers><ReservedEntityID ID="44"/></ReservedEntityIDsFromLayers>'}) as archive:
            context = prepare_scene(archive)
        output = ET.fromstring(context.replacements["objects_mission0.xml"])
        self.assertIsNotNone(output.find('Entity[@Name="treeprop"]'))
        self.assertIsNone(output.find('Entity[@Name="treeprop"]').get("Layer"))
        self.assertIsNone(output.find('Entity[@Name="burningprop"]'))
        self.assertEqual(len(ET.fromstring(context.replacements["layers/town_state0.xml"])), 0)
        self.assertEqual(len(ET.fromstring(context.replacements["layers/town_state1.xml"])), 0)
        self.assertEqual(len(ET.fromstring(context.replacements["whdata_1"]).findall(".//GameProfile")), 0)
        self.assertEqual(len(ET.fromstring(context.replacements["extractedlayerentityids.xml"])), 0)
        self.assertIsNotNone(ET.fromstring(context.replacements["leveldata.xml"]).find('Layers/Layer[@Id="3"]'))

    def test_schema_shells_and_compiled_trigger_cleanup(self):
        trigger = struct.pack('<IIIQfI6f', 3, 20260101, 1, 7, 5., 2, 0., 0., 0., 1., 1., 0.)
        with package('<Objects>'+MARKER+'</Objects>', **{
                'tables/ai/scheduler.xml': b'<database name="barbora"><Schedulers version="1"><Scheduler EntityGuid="27"/></Schedulers></database>',
                'triggerareas.fubar': trigger,
                'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks><WaitingLink SourceId="a" TargetId="b"/></WaitingLinks></StaticLinksInfo>',
                'Scripts/bootstrap.lua': b'unsafe custom start', 'Quests/quest.xml': b'quest'}) as archive:
            context = prepare_scene(archive)
        table = ET.fromstring(context.replacements['tables/ai/scheduler.xml'])
        self.assertEqual(table.attrib, {'name': 'barbora'})
        self.assertEqual(table.find('Schedulers').attrib, {'version': '1'})
        self.assertEqual(len(table.find('Schedulers')), 0)
        self.assertEqual(context.replacements['triggerareas.fubar'], struct.pack('<III', 3, 20260101, 0))
        self.assertEqual(context.report['compiled_gameplay_trigger_areas_removed'], 1)
        self.assertEqual(len(ET.fromstring(context.replacements['waitinglinks.xml']).find('WaitingLinks')), 0)
        self.assertIsNone(transform_level_entry('Scripts/bootstrap.lua', b'anything', context))
        self.assertIsNone(transform_level_entry('Quests/quest.xml', b'anything', context))

    def test_no_guessed_spawn_and_heading_units(self):
        with package('<Objects/>') as archive:
            with self.assertRaisesRegex(ValueError, 'gmtravel_arrival_kcd1'):
                prepare_scene(archive)
            context = prepare_scene(archive, spawn=(1, 2, 3), heading=450)
        self.assertEqual(context.spawn_xyz, (1, 2, 3))
        self.assertEqual(context.heading, 90)
        with package('<Objects/>') as archive:
            with self.assertRaisesRegex(ValueError, 'finite'):
                prepare_scene(archive, spawn=(1, math.nan, 3))

    def test_malformed_native_trigger_data_is_rejected(self):
        for trigger in (b'bad', struct.pack('<III', 1, 3, 0), struct.pack('<III', 3, 42, 1)):
            with package('<Objects>'+MARKER+'</Objects>', **{'triggerareas.fubar': trigger}) as archive:
                with self.assertRaises(ValueError):
                    prepare_scene(archive)

    def test_conflicting_entity_ids_and_reserved_actor_guid_are_rejected(self):
        for objects in (
            '<Objects>'+MARKER+'<Entity EntityId="10" EntityClass="GeomEntity" Geometry="objects/x.cgf"/></Objects>',
            '<Objects>'+MARKER+'<Entity EntityId="22" EntityGuid="00007777-0000-0000" EntityClass="GeomEntity" Geometry="objects/x.cgf"/></Objects>',
        ):
            with package(objects) as archive:
                with self.assertRaises(ValueError):
                    prepare_scene(archive)

    def test_reserved_numeric_id_is_remapped_with_links_and_parent_transform(self):
        for reserved_id in ('30583', '030583'):
            objects = ('<Objects>'+MARKER+
                f'<Entity EntityId="{reserved_id}" EntityGuid="357da218-c0bb-1f5d" Name="window" EntityClass="ReflexLight" Pos="10,20,30"><Properties Radius="5"/></Entity>'
                '<Entity EntityId="1" EntityGuid="00000001-0000-0000" Name="child" EntityClass="Light" ParentId="30583" Pos="1,2,3"><EntityLinks>'
                '<Link Name="light" TargetId="030583" TargetGuid="357da218-c0bb-1f5d"/>'
                '</EntityLinks></Entity>'
                '<Entity EntityId="65533" Name="highest" EntityClass="TagPoint"/>'
                '</Objects>')
            with package(objects) as archive:
                context = prepare_scene(archive)
                self.assertEqual(context.replacements, prepare_scene(archive).replacements)
            output = ET.fromstring(context.replacements['objects_mission0.xml'])
            window = output.find('Entity[@Name="window"]')
            child = output.find('Entity[@Name="child"]')
            self.assertNotEqual(window.get('EntityId'), '30583')
            self.assertEqual(window.get('EntityGuid'), '357da218-c0bb-1f5d')
            self.assertEqual(window.find('Properties').get('Radius'), '5')
            self.assertEqual(child.get('Pos'), '11,22,33')
            self.assertEqual(child.find('EntityLinks/Link').get('TargetId'), window.get('EntityId'))
            ids = [e.get('EntityId') for e in output]
            self.assertNotIn('30583', ids)
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(len(context.report['remapped_entity_ids']), 1)
            souls = ET.fromstring(context.replacements['whdata_0'])
            self.assertEqual(souls.findtext('.//Soul/EntityGuid'), '30583')

    def test_stale_dual_link_endpoint_is_not_kept(self):
        objects = ('<Objects>'+MARKER+
                   '<Entity EntityId="1" EntityGuid="00000001-0000-0000" EntityClass="Light"><EntityLinks>'
                   '<Link Name="stale" TargetId="2" TargetGuid="00000003-0000-0000"/>'
                   '</EntityLinks></Entity>'
                   '<Entity EntityId="2" EntityGuid="00000002-0000-0000" EntityClass="ClipVolume"/>'
                   '<Entity EntityId="3" EntityGuid="00000003-0000-0000" EntityClass="QuestObject"/>'
                   '</Objects>')
        with package(objects) as archive:
            context = prepare_scene(archive)
        self.assertEqual(len(ET.fromstring(context.replacements['objects_mission0.xml']).findall('.//EntityLinks/Link')), 0)
        self.assertEqual(context.report['pruned_entity_links'], 1)

    def test_player_bootstrap_record_retains_all_source_fields(self):
        player = ('<Soul><Player>1</Player><EntityGuid>30583</EntityGuid><Guid>777</Guid>'
                  '<SharedSoulGuid>888</SharedSoulGuid><StaticData keep="true"><Name>player</Name></StaticData></Soul>')
        source = ('<Root><SoulList><Souls>'+player+
                  '<Soul><Player>0</Player><Guid>999</Guid></Soul></Souls></SoulList></Root>')
        with package('<Objects>'+MARKER+'</Objects>', **{'whdata_0': source,
                'smartobjecthelpersetanimations.xml': b'<SmartObjectAnimationCollections><SmartObjectHelperSetAnimationCollection Name="old"/></SmartObjectAnimationCollections>'}) as archive:
            context = prepare_scene(archive)
        retained = ET.fromstring(context.replacements['whdata_0']).find('SoulList/Souls/Soul')
        self.assertEqual(ET.tostring(retained), ET.tostring(ET.fromstring(player)))
        self.assertEqual(len(ET.fromstring(context.replacements['smartobjecthelpersetanimations.xml'])), 0)

    def test_excluded_later_state_does_not_replace_initial_geometry(self):
        initial = '<Entity EntityId="11" Name="house" EntityClass="GeomEntity" Geometry="objects/intact.cgf"/>'
        later = '<Objects><Entity EntityId="11" Name="house" EntityClass="GeomEntity" Geometry="objects/burned.cgf"/></Objects>'
        with package('<Objects>'+MARKER+initial+'</Objects>', **{'layers/town_state1.xml': later}) as archive:
            context = prepare_scene(archive)
        house = ET.fromstring(context.replacements['objects_mission0.xml']).find('Entity[@Name="house"]')
        self.assertEqual(house.get('Geometry'), 'objects/intact.cgf')


if __name__ == '__main__':
    unittest.main()
