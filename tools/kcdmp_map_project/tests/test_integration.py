"""Asset-free export integration tests; these do not run KCD2 or KCDMP.

Optional inspection of the actual supplied distributions:

    KCDMP_TEST_CLIENT_ZIP=/path/to/KcdMp-0.44.0-win-x64.zip
    KCDMP_TEST_SERVER_ZIP=/path/to/KcdMp-server-0.44.0.zip
    python -m unittest discover -s tests -v

Set either or both environment variables. The optional test hashes files and
reads ZIP members only; it never starts a packaged executable.
"""
from __future__ import annotations

from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from kcdmp_bridge import builder
from kcdmp_bridge.archive import BridgeError
from kcdmp_bridge.profile import check_mod
from kcdmp_bridge.scene import SPAWN_NAME


def write_zip(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def file_snapshot(path: Path) -> dict[str, str]:
    return {item.relative_to(path).as_posix(): sha256(item.read_bytes()).hexdigest()
            for item in sorted(path.rglob("*")) if item.is_file()}


def xml_text(text: str) -> bytes:
    return text.encode("utf-8")


class BuildIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kcdmp-synthetic-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.game = self.root / "synthetic-game"
        self.source = self.game / "Mods/kingdomcomegluemapper"
        self.level = self.source / "Data/Levels/kcd1_travel"
        self.client = self.root / "synthetic-client"
        self.server = self.root / "synthetic-server"
        self.client.mkdir()
        self.server.mkdir()
        self.source.mkdir(parents=True)
        (self.source / "mod.manifest").write_text(
            '<kcd_mod><info><modid>kingdomcomegluemapper</modid></info></kcd_mod>',
            encoding="utf-8")
        # These files are deliberately synthetic. Retail build fingerprinting is
        # mocked below; archive parsing and all export transformations are real.
        (self.game / "system.cfg").write_text('wh_sys_version = "1.5.6"\n', encoding="utf-8")
        (self.game / "Mods/mod_order.txt").write_bytes(b"another_mod\r\nkingdomcomegluemapper\r\n")
        write_zip(self.game / "Data/Tables.pak", {
            "Libs/Tables/level.xml": xml_text(
                '<database name="barbora"><levels version="1">'
                '<LevelData LevelId="1" LevelName="trosecko"/>'
                '<LevelData LevelId="2" LevelName="kutnohorsko"/>'
                '</levels></database>'),
        })
        write_zip(self.game / "Data/Scripts.pak", {
            "Scripts/Entities/actor/player.lua": b"synthetic native player script, never executed",
        })

        self.registration = {
            "LevelId": "1001", "LevelName": "kcd1_travel",
            "LevelPath": "data/levels/kcd1_travel", "DisplayName": "Synthetic KCD1 map",
        }
        row = ET.Element("LevelData", self.registration)
        registry = ET.Element("database", name="barbora")
        levels = ET.SubElement(registry, "levels", version="1")
        levels.append(row)
        ET.SubElement(levels, "LevelData", LevelId="1500", LevelName="unrelated_source_level")

        self.kept_assets = {
            "gluebuild/objects/house.cgf": b"synthetic mesh\x00\x13\xff",
            "gluebuild/materials/house.mtl": b'<Material Name="synthetic"/>',
            "textures/ground.dds": b"synthetic texture\x00\x81",
            "Libs/UI/Textures/map.dds": b"synthetic map image resource",
        }
        self.disallowed_assets = {
            "Scripts/Entities/actor/player.lua": b"campaign player override",
            "Scripts/Startup/GlueMapper.lua": b"campaign startup hook",
            "Quests/starting_quest.xml": b"campaign quest",
            "Libs/UI/Frontend/mainmenu.gfx": b"campaign menu override",
            "Libs/Tables/soul__kingdomcomegluemapper.xml": b"campaign global soul table",
            "Libs/Storm/campaign.xml": b"campaign registration",
            "GlueMapper/CampaignSource/quest.xml": b"embedded campaign source",
            "Mods/kingdomcomegluemapper/Data/Levels/kcd1_travel/Tables/ai/scheduler.xml": b"old campaign alias",
        }
        self.mixed_name = "000_mixed_assets_and_campaign.pak"
        write_zip(self.source / "Data" / self.mixed_name, {
            **self.kept_assets, **self.disallowed_assets,
            "Libs/Tables/level__kingdomcomegluemapper.xml": ET.tostring(registry),
        })
        self.pure_name = "001_pure_rendering_assets.pak"
        write_zip(self.source / "Data" / self.pure_name, {
            "objects/vegetation/tree.cgf": b"synthetic untouched pure asset pack",
        })

        self.svo = b"opaque synthetic SVO payload\x00\xff\x10\x13"
        self.hlod = b"opaque synthetic HLOD payload\x00\x11\xfe"
        self.terrain = b"opaque synthetic terrain bytes\x00\x01\xff"
        marker = (
            '<Entity Name="gmtravel_arrival_kcd1" EntityClass="TagPoint" '
            'EntityId="10" EntityGuid="0000000a-0000-0000" '
            'Pos="3831.58,1787.66,127.43" '
            'Rotate="0.7071067811865476,0,0,0.7071067811865476"/>')
        objects = (
            '<Objects>' + marker +
            '<Entity Name="house" EntityClass="GeomEntity" EntityId="11" '
            'Geometry="gluebuild/objects/house.cgf" Pos="1,2,3">'
            '<Properties bSaved_by_game="1"/><FlowGraph><StartQuest/></FlowGraph></Entity>'
            '<Entity Name="sky-light" EntityClass="EnvironmentLight" EntityId="12">'
            '<Properties bActive="1"/></Entity>'
            '<Entity Name="story" EntityClass="Concept" EntityId="13"/>'
            '<Entity Name="campaign-person" EntityClass="NPC" EntityId="14"/>'
            '<Entity Name="kcd1_travel" EntityClass="LevelHolder" EntityId="15"/>'
            '</Objects>')
        write_zip(self.level / "level.pak", {
            "objects_mission0.xml": xml_text(objects),
            "mission_mission0.xml": xml_text(
                '<Mission><Environment><EnvState UseLayersActivation="1" SunIntensity="4"/>'
                '</Environment><Script File="campaign.lua"/></Mission>'),
            "levelinfo.xml": b'<LevelInfo Name="data/levels/kcd1_travel"/>',
            "leveldata.xml": b'<LevelData><Layers/><GameTokensLibraryReferences><Library File="campaign.xml"/></GameTokensLibraryReferences></LevelData>',
            "whdata_0": xml_text(
                '<Root version="1"><ConceptManager><ConceptPaths><Path>quests/start.xml</Path></ConceptPaths>'
                '<ConceptModules><Module>start</Module></ConceptModules></ConceptManager>'
                '<AI><LevelPath>data/levels/kcd1_travel</LevelPath>'
                '<SmartAreaManager version="2"><SmartAreas><SmartArea><Guid>17</Guid>'
                '</SmartArea></SmartAreas></SmartAreaManager></AI>'
                '<SoulList><Souls><Soul><Name>native_player</Name><Player>1</Player>'
                '<EntityGuid>30583</EntityGuid></Soul><Soul><Name>campaign_npc</Name><Player>0</Player>'
                '</Soul></Souls></SoulList></Root>'),
            "tables/ai/scheduler.xml": b'<database name="barbora"><Schedulers version="1"><Scheduler EntityGuid="17"/></Schedulers></database>',
            "smartobjecthelpersetanimations.xml": b'<SmartObjectHelperSetAnimations version="1"><Animation Name="campaign_work"/></SmartObjectHelperSetAnimations>',
            "triggerareas.fubar": struct.pack("<IIIQfI6f", 3, 20260101, 1, 7, 5., 2, 0., 0., 0., 1., 1., 0.),
            "Scripts/bootstrap.lua": b"campaign level script",
            "Quests/quest.xml": b"campaign level quest",
            "terrain/hlods.dat": self.hlod,
            "terrain/svo/0_0_0.dat": self.svo,
        })
        write_zip(self.level / "terrain.pak", {"terrain/heightmap.dat": self.terrain})
        write_zip(self.level / "svogi/cells.pak", {"terrain/svo/cells.bin": self.svo})

    def options(self, **changes) -> builder.BuildOptions:
        arguments = dict(game=self.game, source_mod=self.source, client=self.client,
                         server=self.server, output=self.root / "exported-profile")
        arguments.update(changes)
        return builder.BuildOptions(**arguments)

    def mock_external_checks(self):
        context = ExitStack()
        context.enter_context(patch.object(builder, "inspect_game", return_value={
            "root": str(self.game), "version": "1.5.6", "matching_builds": [{"build_id": "synthetic"}],
        }))
        context.enter_context(patch.object(builder, "check_distribution", side_effect=lambda path, kind: {
            "kind": kind, "source": str(path), "zip": False, "synthetic": True,
        }))
        context.enter_context(patch.object(builder, "materialize_runtime", side_effect=lambda record, output: Path(record["source"])))
        # Export must never start a game or distribution binary, including on Windows.
        context.enter_context(patch("subprocess.run", side_effect=AssertionError("The builder started a process")))
        context.enter_context(patch("subprocess.Popen", side_effect=AssertionError("The builder started a process")))
        return context

    def test_setup_export_retains_shaders_and_copies_temporary_runtimes(self):
        shaders=self.source/'ShaderCache/Engine';shaders.mkdir(parents=True)
        (shaders/'Shaders.pak').write_bytes(b'synthetic compiled shaders')
        (self.client/'client.dat').write_bytes(b'client input')
        (self.server/'server.dat').write_bytes(b'server input')
        before=file_snapshot(self.game)
        with self.mock_external_checks():
            p=builder.build(self.options(standalone=False,portable_runtime=True),progress=lambda _:None)
        self.assertEqual(file_snapshot(self.game),before)
        self.assertEqual((Path(p['mod'])/'ShaderCache/Engine/Shaders.pak').read_bytes(),b'synthetic compiled shaders')
        receipt=check_mod(Path(p['mod']),full=True)
        self.assertIn('ShaderCache/Engine/Shaders.pak',receipt['files'])
        self.assertEqual((Path(p['client'])/'client.dat').read_bytes(),b'client input')
        self.assertEqual((Path(p['server'])/'server.dat').read_bytes(),b'server input')
        self.assertNotEqual(Path(p['client']),self.client)
        self.assertFalse((Path(p['output'])/'bridge_tool').exists())
        self.assertFalse(list(Path(p['output']).glob('*.cmd')))

    def test_setup_level_upgrade_precedes_receipt_hashes_and_preserves_source(self):
        before=file_snapshot(self.source)
        def upgrade(mod, level):
            self.assertEqual(level,builder.LEVEL)
            path=mod/'Data/Levels'/level/'terrain.pak'
            with zipfile.ZipFile(path,'a') as archive:
                archive.writestr('terrain/test-placement-marker',b'upgraded')
            return {'version':1}
        with self.mock_external_checks():
            profile=builder.build(self.options(standalone=False),progress=lambda _:None,upgrade_level=upgrade)
        report=check_mod(Path(profile['mod']),full=True)
        self.assertEqual(report['level_package']['surface_placement'],{'version':1})
        self.assertEqual(file_snapshot(self.source),before)

    def test_build_filters_campaign_and_preserves_rendering_payloads(self):
        before = file_snapshot(self.game)
        options = self.options(spawn=(100.25, 200.5, 30.125), yaw=271.25)
        messages = []
        with self.mock_external_checks():
            profile = builder.build(options, progress=messages.append)
        self.assertEqual(file_snapshot(self.game), before, "Export modified the original game/conversion")
        self.assertEqual(file_snapshot(self.client), {})
        self.assertEqual(file_snapshot(self.server), {})
        self.assertFalse((self.game / ".gluemapper-kcdmp").exists())
        self.assertEqual(profile["spawn"], {"xyz": [100.25, 200.5, 30.125], "yaw_degrees": 271.25})
        self.assertFalse(profile["runtime_verified"])
        self.assertTrue(messages[-1].startswith("Built "))

        mod = Path(profile["mod"])
        self.assertEqual(ET.parse(mod / "mod.manifest").findtext("./info/modid"), "gluemapperkcdmp")
        with zipfile.ZipFile(mod / "Data" / self.mixed_name) as archive:
            self.assertEqual(set(archive.namelist()), set(self.kept_assets))
            for name, payload in self.kept_assets.items():
                self.assertEqual(archive.read(name), payload)
        for relative in ("Data/" + self.pure_name, "Data/Levels/kcd1_travel/terrain.pak",
                         "Data/Levels/kcd1_travel/svogi/cells.pak"):
            self.assertEqual((mod / relative).read_bytes(), (self.source / relative).read_bytes(), relative)

        with zipfile.ZipFile(mod / "Data/Levels/kcd1_travel/level.pak") as archive:
            self.assertEqual(archive.read("terrain/hlods.dat"), self.hlod)
            self.assertEqual(archive.read("terrain/svo/0_0_0.dat"), self.svo)
            self.assertNotIn("Scripts/bootstrap.lua", archive.namelist())
            self.assertNotIn("Quests/quest.xml", archive.namelist())
            entities = ET.fromstring(archive.read("objects_mission0.xml"))
            classes = {entity.get("EntityClass") for entity in entities}
            self.assertTrue({"GeomEntity", "EnvironmentLight", "SpawnPoint"} <= classes)
            self.assertTrue({"NPC", "Concept", "LevelHolder"}.isdisjoint(classes))
            self.assertIsNone(entities.find(".//FlowGraph"))
            spawn = entities.find(f'Entity[@Name="{SPAWN_NAME}"]')
            self.assertEqual(spawn.get("Pos"), "100.25,200.5,30.125")
            mission = ET.fromstring(archive.read("mission_mission0.xml"))
            self.assertIsNone(mission.find("Script"))
            self.assertEqual(mission.find("Environment/EnvState").get("SunIntensity"), "4")
            self.assertEqual(mission.find("Environment/EnvState").get("UseLayersActivation"), "0")
            world = ET.fromstring(archive.read("whdata_0"))
            self.assertEqual([s.findtext("Name") for s in world.findall("SoulList/Souls/Soul")], ["native_player"])
            self.assertEqual(len(world.findall(".//SmartArea")), 0)
            self.assertEqual(archive.read("triggerareas.fubar"), struct.pack("<III", 3, 20260101, 0))
            animations = ET.fromstring(archive.read("smartobjecthelpersetanimations.xml"))
            self.assertEqual(len(animations), 0, "Prepared scene metadata must actually be written into level.pak")
            cleaned_table = archive.read("tables/ai/scheduler.xml")
            table = ET.fromstring(cleaned_table)
            self.assertEqual(table.attrib, {"name": "barbora"})
            self.assertEqual(table.find("Schedulers").attrib, {"version": "1"})
            self.assertEqual(len(table.find("Schedulers")), 0)

        with zipfile.ZipFile(mod / "Data/zzz_gluemapperkcdmp_registration.pak") as archive:
            self.assertEqual(set(archive.namelist()), {
                "Libs/Tables/level__gluemapperkcdmp.xml",
                "Mods/gluemapperkcdmp/Data/Levels/kcd1_travel/tables/ai/scheduler.xml",
            })
            registry = ET.fromstring(archive.read("Libs/Tables/level__gluemapperkcdmp.xml"))
            self.assertEqual([row.attrib for row in registry.findall("./levels/LevelData")], [self.registration])
            self.assertEqual(archive.read("Mods/gluemapperkcdmp/Data/Levels/kcd1_travel/tables/ai/scheduler.xml"), cleaned_table)

        server = Path(profile["server_profile"])
        configuration = tomllib.loads((server / "server.kcd1-map-only.toml").read_text(encoding="utf-8"))
        self.assertEqual(configuration["server"]["level"], "kcd1_travel")
        self.assertEqual(configuration["mods"], {"policy": "allow_list", "allowed": ["gluemapperkcdmp"], "refused": []})
        self.assertEqual(configuration["master"]["url"], "")
        self.assertEqual({key: configuration["spawn"][key] for key in ("x", "y", "z", "yaw")},
                         {"x": 100.25, "y": 200.5, "z": 30.125, "yaw": 271.25})
        self.assertEqual(configuration["spawn"]["items"], [])
        lua = (server / "gamemodes/kcd1_map_only.lua").read_text(encoding="utf-8")
        self.assertNotIn("@@", lua)
        for declaration in ("x = 100.25", "y = 200.5", "z = 30.125", "yaw = 271.25", "SetStoryQuests(false)"):
            self.assertIn(declaration, lua)

        receipt = check_mod(mod, full=True)
        self.assertFalse(receipt["runtime_verified"])
        self.assertEqual(receipt["source"]["spawn"], profile["spawn"])
        self.assertEqual(json.loads((options.output / "build-report.json").read_text()), receipt)
        for filename in ("1_ACTIVATE_MAP.cmd", "2_START_SERVER.cmd", "3_JOIN_LOCAL_SERVER.cmd",
                         "OFFLINE_MAP_TEST.cmd", "RESTORE_MODS.cmd", "VERIFY_PROFILE.cmd", "START_HERE.txt"):
            self.assertTrue((options.output / filename).is_file(), filename)
        self.assertTrue((options.output / "bridge_tool/patch.py").is_file())
        self.assertTrue((options.output / "bridge_tool/templates/server.toml.template").is_file())

    def test_build_uses_the_authored_spawn_when_no_override_is_given(self):
        before = file_snapshot(self.game)
        with self.mock_external_checks():
            profile = builder.build(self.options(), progress=lambda message: None)
        self.assertEqual(profile["spawn"]["xyz"], [3831.58, 1787.66, 127.43])
        self.assertAlmostEqual(profile["spawn"]["yaw_degrees"], 90)
        config = tomllib.loads((Path(profile["server_profile"]) / "server.kcd1-map-only.toml").read_text())
        self.assertEqual([config["spawn"][key] for key in ("x", "y", "z")], profile["spawn"]["xyz"])
        self.assertEqual(config["spawn"]["yaw"], 90)
        self.assertEqual(file_snapshot(self.game), before)

    def test_native_level_id_collision_stops_before_creating_output(self):
        write_zip(self.game / "Data/Tables.pak", {
            "Libs/Tables/level.xml": b'<database><levels><LevelData LevelId="1001" LevelName="a_native_level"/></levels></database>',
        })
        before = file_snapshot(self.game)
        options = self.options()
        with self.mock_external_checks():
            with self.assertRaisesRegex(BridgeError, "collides"):
                builder.build(options, progress=lambda message: None)
        self.assertFalse(options.output.exists())
        self.assertEqual(file_snapshot(self.game), before)


class InspectedDistributionTests(unittest.TestCase):
    def test_optional_supplied_archive_hashes_match_the_evidence(self):
        names = (
            ("KCDMP_TEST_CLIENT_ZIP", "client", "KcdMp-0.44.0-win-x64.zip"),
            ("KCDMP_TEST_SERVER_ZIP", "server", "KcdMp-server-0.44.0.zip"),
        )
        selected = [(os.environ[variable], kind, name) for variable, kind, name in names if os.environ.get(variable)]
        if not selected:
            self.skipTest("Set KCDMP_TEST_CLIENT_ZIP and/or KCDMP_TEST_SERVER_ZIP for read-only distribution validation")
        records = builder.evidence()
        for source, kind, name in selected:
            with self.subTest(distribution=name):
                path = Path(source).expanduser().resolve()
                record = builder.check_distribution(path, kind)
                expected = records[name]
                self.assertTrue(record["zip"])
                self.assertEqual(record["sha256"], expected["sha256"])
                self.assertEqual(path.stat().st_size, expected["bytes"])
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(len(archive.infolist()), expected["entries"])
                    for member, fingerprint in expected["binaries"].items():
                        payload = archive.read(member)
                        self.assertEqual(len(payload), fingerprint["bytes"], member)
                        self.assertEqual(sha256(payload).hexdigest(), fingerprint["sha256"], member)


if __name__ == "__main__":
    unittest.main()
