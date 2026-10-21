import tempfile
import unittest
from pathlib import Path
import zipfile

from kcdmp_bridge.archive import BridgeError, asset_allowed, checked_infos, rewrite_assets, safe_name


class ArchiveTests(unittest.TestCase):
    def test_mixed_archive_preserves_asset_bytes_and_removes_boot_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / "source.pak", root / "out/result.pak"
            assets = {"Objects/fixture.cgf": b"geometry\0\xff", "textures/probe.dds.1": b"probe mip",
                      "Libs/UI/Textures/Maps/global_map_gluemapper_rataje_0.dds": b"cartography"}
            unwanted = {"Scripts/Entities/actor/player.lua": b"boot()", "Quests/GlueTravel/entry.xml": b"<story/>",
                        "Mods/kingdomcomegluemapper/Data/Levels/kcd1_travel/tables/ai.xml": b"<old/>",
                        "Libs/Tables/level__kingdomcomegluemapper.xml": b"<old/>", "libs/ui/menu.gfx": b"menu",
                        "Levels/kcd1_travel/objects_mission0.xml": b"<unsanitized/>",
                        "Levels/kcd1_travel/whdata_0": b"<boot/>",
                        "Levels/kcd1_travel/smartobjecthelpersetanimations.xml": b"<gameplay/>"}
            with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in {**assets, **unwanted}.items():
                    archive.writestr(name, data)
            before = source.read_bytes()
            report = rewrite_assets(source, target)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(set(archive.namelist()), set(assets))
                for name, data in assets.items():
                    self.assertEqual(archive.read(name), data)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(set(report["dropped_entries"]), set(unwanted))

    def test_pure_render_archive_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "source.pak", "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("glueveg/tree.cgf", b"native render bytes")
            report = rewrite_assets(root / "source.pak", root / "copy.pak")
            self.assertTrue(report["byte_identical"])
            self.assertEqual((root / "source.pak").read_bytes(), (root / "copy.pak").read_bytes())

    def test_path_traversal_windows_aliases_and_case_duplicates_rejected(self):
        for name in ("../outside", "a/../outside", "/root", "C:/outside", "a:N", "a/CON.txt", "a./x", "a//b", "a\x00b"):
            with self.subTest(name=name), self.assertRaises(BridgeError):
                safe_name(name)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Textures/A.dds", b"first")
                archive.writestr("textures/a.dds", b"second")
            with zipfile.ZipFile(path) as archive, self.assertRaises(BridgeError):
                checked_infos(archive)

    def test_nested_level_override_never_escapes_scene_cleaner(self):
        self.assertTrue(asset_allowed("Levels/kcd1_travel/textures/probe.dds"))
        for name in ("levels/kcd1_travel/layers/new.xml", "levels/kcd1_travel/level.pak",
                     "levels/kcd1_travel/triggerareas.fubar", "levels/kcd1_travel/tables/ai/scheduler.xml",
                     "levels/kcd1_travel/quests/story.xml"):
            self.assertFalse(asset_allowed(name), name)


if __name__ == "__main__":
    unittest.main()
