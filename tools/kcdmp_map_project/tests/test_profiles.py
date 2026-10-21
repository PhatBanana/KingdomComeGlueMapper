"""Filesystem recovery and native CLI contracts; no supplied binary is run."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from kcdmp_bridge.archive import BridgeError, sha256
from kcdmp_bridge.builder import LEVEL, MOD_ID, RECEIPT
from kcdmp_bridge import builder as builders
from kcdmp_bridge import profile as profiles


class ProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.game = self.root / "Game With Spaces"
        self.output = self.root / "Map Export"
        self.mod = self.output / "client_mod" / MOD_ID
        self.order = self.game / "Mods/mod_order.txt"
        self.order.parent.mkdir(parents=True)
        original_mod = self.game / "Mods/kingdomcomegluemapper"
        original_mod.mkdir()
        self.original_asset = original_mod / "original.pak"
        self.original_asset.write_bytes(b"unchanged single-player conversion")
        self.files = {
            "mod.manifest": (f"<kcd_mod><info><modid>{MOD_ID}</modid></info></kcd_mod>").encode(),
            f"Data/Levels/{LEVEL}/level.pak": b"synthetic cleaned scene",
            f"Data/Levels/{LEVEL}/levelinfo.xml": b"<LevelInfo/>",
            "Data/assets.pak": b"synthetic rendering payload",
        }
        for name, data in self.files.items():
            target = self.mod / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        registry = self.mod / "Data/zzz_gluemapperkcdmp_registration.pak"
        with zipfile.ZipFile(registry, "w") as archive:
            archive.writestr(f"Libs/Tables/level__{MOD_ID}.xml",
                             f"<table><levels><LevelData LevelName='{LEVEL}' LevelId='1001'/></levels></table>")
        records = {p.relative_to(self.mod).as_posix(): {"bytes": p.stat().st_size, "sha256": sha256(p)}
                   for p in self.mod.rglob("*") if p.is_file()}
        (self.mod / RECEIPT).write_text(json.dumps({"owner": MOD_ID, "schema": 1,
                                                   "level": LEVEL, "files": records}), encoding="utf-8")
        self.profile = {"schema": 1, "owner": MOD_ID, "level": LEVEL,
                        "game": str(self.game), "output": str(self.output), "mod": str(self.mod),
                        "client": str(self.output / "runtime/client"),
                        "server": str(self.output / "runtime/server"),
                        "server_profile": str(self.output / "server-profile"),
                        "name": "SamGCoder", "host": "127.0.0.1:7777",
                        "spawn": {"xyz": [3831.58, 1787.66, 127.43], "yaw_degrees": 90}}
        for target in ("game_stopped", "inspect_game"):
            patcher = mock.patch.object(profiles, target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def activate(self):
        return profiles.activate(self.profile, progress=lambda _: None)

    def restore(self):
        return profiles.restore_game(self.game, progress=lambda _: None)

    def assert_original_preserved(self):
        self.assertEqual(self.original_asset.read_bytes(), b"unchanged single-player conversion")
        for name, data in self.files.items():
            self.assertEqual((self.mod / name).read_bytes(), data)

    def test_client_argv_uses_server_query_and_clears_inherited_overrides(self):
        inherited = {"PATH": "ordinary search path", "KCDMP_SERVER_LEVEL": "trosecko",
                     "KcdMp_story_quests": "1", "KCDMP_MAP": "trosecko"}
        with mock.patch.dict(os.environ, inherited, clear=True), \
                mock.patch.object(profiles, "check_distribution"), \
                mock.patch.object(profiles, "require_active"):
            args, cwd, env = profiles.launch_spec(self.profile, "client")
        self.assertEqual(args, [str(Path(self.profile["client"]) / "KcdMp_launcher.exe"),
                                "--game", str(self.game), "--name", "SamGCoder",
                                "--connect", "127.0.0.1:7777"])
        self.assertEqual(cwd, Path(self.profile["client"]))
        self.assertEqual(env, {"PATH": "ordinary search path"})
        self.assertNotIn("--update", args)
        self.assertNotIn("--skip-build-check", args)

    def test_offline_spawn_is_one_comma_delimited_native_argument(self):
        with mock.patch.object(profiles, "check_distribution"), \
                mock.patch.object(profiles, "require_active"):
            args, cwd, _ = profiles.launch_spec(self.profile, "offline")
        self.assertEqual(args[-5:], ["--map", LEVEL, "--", "-KcdMp_spawn", "3831.58,1787.66,127.43,90"])
        self.assertNotIn("--connect", args)
        self.assertEqual(cwd, Path(self.profile["client"]))

    def test_server_config_and_relative_data_use_profile_directory(self):
        with mock.patch.object(profiles, "check_distribution") as check:
            args, cwd, _ = profiles.launch_spec(self.profile, "server")
        self.assertEqual(cwd, Path(self.profile["server_profile"]))
        self.assertEqual(args, [str(Path(self.profile["server"]) / "KcdMp.Server.exe"),
                                "--config", str(cwd / "server.kcd1-map-only.toml")])
        check.assert_called_once_with(Path(self.profile["server"]), "server")

    def test_roundtrip_restores_exact_order_bytes_and_preserves_originals(self):
        original = b"\xef\xbb\xbfkingdomcomegluemapper\r\n# user comment\r\nother-mod\r\n"
        self.order.write_bytes(original)
        active = self.activate()
        self.assertEqual(self.order.read_bytes(), (MOD_ID + "\n").encode())
        self.assertEqual(profiles.require_active(self.profile), self.game / "Mods" / MOD_ID)
        restored = self.restore()
        self.assertEqual(self.order.read_bytes(), original)
        self.assertFalse((self.game / "Mods" / MOD_ID).exists())
        self.assertEqual(restored["phase"], "restored")
        self.assertTrue((Path(restored["preserved_map"]) / RECEIPT).is_file())
        self.assertFalse((self.game / ".gluemapper-kcdmp/active.json").exists())
        self.assertTrue((self.game / ".gluemapper-kcdmp" / ("restored-" + active["token"] + ".json")).is_file())
        self.assert_original_preserved()

    def test_roundtrip_restores_absence_of_order_file(self):
        self.assertFalse(self.order.exists())
        self.activate()
        self.restore()
        self.assertFalse(self.order.exists())
        self.assert_original_preserved()

    def test_partial_stage_failure_can_restore_without_installing_or_losing_source(self):
        original = b"kingdomcomegluemapper\r\n"
        self.order.write_bytes(original)
        with mock.patch.object(profiles, "copy_file", side_effect=OSError("simulated disk interruption")):
            with self.assertRaises(OSError):
                self.activate()
        self.assertEqual(self.order.read_bytes(), original)
        self.assertFalse((self.game / "Mods" / MOD_ID).exists())
        restored = self.restore()
        self.assertTrue(Path(restored["preserved_map"]).is_dir())
        self.assertEqual(self.order.read_bytes(), original)
        self.assert_original_preserved()

    def test_failed_mod_order_write_restores_installed_stage(self):
        original = b"kingdomcomegluemapper\r\n"
        self.order.write_bytes(original)
        with mock.patch.object(profiles, "atomic_bytes", side_effect=OSError("simulated locked mod_order")):
            with self.assertRaises(OSError):
                self.activate()
        self.assertTrue((self.game / "Mods" / MOD_ID / RECEIPT).is_file())
        self.assertEqual(self.order.read_bytes(), original)
        restored = self.restore()
        self.assertEqual(self.order.read_bytes(), original)
        self.assertTrue((Path(restored["preserved_map"]) / RECEIPT).is_file())
        self.assert_original_preserved()

    def test_interruption_after_order_change_restores_previous_bytes(self):
        original = b"\r\nkingdomcomegluemapper\r\n"
        self.order.write_bytes(original)
        real_write = profiles.atomic_json

        def interrupted(path, payload):
            if path.name == "active.json" and payload["phase"] == "active":
                raise KeyboardInterrupt()
            return real_write(path, payload)

        with mock.patch.object(profiles, "atomic_json", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.activate()
        self.assertEqual(self.order.read_bytes(), (MOD_ID + "\n").encode())
        self.restore()
        self.assertEqual(self.order.read_bytes(), original)
        self.assert_original_preserved()

    def test_restore_refuses_to_overwrite_a_new_user_mod_selection(self):
        self.order.write_bytes(b"kingdomcomegluemapper\n")
        self.activate()
        user_edit = b"some-new-selection\n"
        self.order.write_bytes(user_edit)
        with self.assertRaisesRegex(BridgeError, "edited after activation"):
            self.restore()
        self.assertEqual(self.order.read_bytes(), user_edit)
        self.assertTrue((self.game / "Mods" / MOD_ID).exists())
        self.assertTrue((self.game / ".gluemapper-kcdmp/active.json").exists())
        self.assert_original_preserved()

    def test_existing_destination_is_never_overwritten(self):
        existing = self.game / "Mods" / MOD_ID
        existing.mkdir()
        note = existing / "my-edits.txt"
        note.write_text("existing user files", encoding="utf-8")
        with self.assertRaisesRegex(BridgeError, "already exists"):
            self.activate()
        self.assertEqual(note.read_text(encoding="utf-8"), "existing user files")
        self.assertFalse((self.game / ".gluemapper-kcdmp/active.json").exists())


class GameBuildSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.game = Path(temp.name).resolve() / "Retail Game"
        (self.game / "Data").mkdir(parents=True)
        (self.game / "system.cfg").write_text('wh_sys_version = "1.5.6"\n', encoding="utf-8")
        for name in ("Tables.pak", "Scripts.pak"):
            (self.game / "Data" / name).write_bytes(b"synthetic package presence")
        self.known = {"steam": b"known steam test bytes", "msstore": b"known msstore test bytes"}
        builds = [{"store": store, "id": store + "-fixture", "game_version": "1.5.6",
                   "whgame": {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}}
                  for store, data in self.known.items()]
        patcher = mock.patch.object(builders, "evidence", return_value={
            "KcdMp-0.44.0-win-x64.zip": {"supported_builds": builds}})
        patcher.start()
        self.addCleanup(patcher.stop)

    def binary_directory(self, relative: str, data: bytes):
        directory = self.game / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "KingdomCome.exe").write_bytes(b"synthetic executable presence; never run")
        (directory / "WHGame.dll").write_bytes(data)
        return directory

    def test_steam_requires_the_launcher_selected_binary_directory(self):
        directory = self.binary_directory("Bin/Win64MasterMasterSteamPGO", self.known["steam"])
        result = builders.inspect_game(self.game)
        self.assertEqual(result["store"], "steam")
        self.assertEqual(result["executable"], str(directory / "KingdomCome.exe"))
        self.assertEqual(result["matching_builds"][0]["path"], str(directory / "WHGame.dll"))

    def test_msstore_validates_dll_at_content_root_without_bin(self):
        self.binary_directory("", self.known["msstore"])
        (self.game / "MicrosoftGame.Config").write_text(
            '<Game><Identity Name="DeepSilver.77536C3FE941"/></Game>', encoding="utf-8")
        result = builders.inspect_game(self.game)
        self.assertEqual(result["store"], "msstore")
        self.assertEqual(result["executable"], str(self.game / "KingdomCome.exe"))
        self.assertEqual(result["matching_builds"][0]["path"], str(self.game / "WHGame.dll"))

    def test_supported_backup_does_not_certify_an_unsupported_active_engine(self):
        self.binary_directory("Bin/Win64MasterMasterSteamPGO", b"unsupported active engine")
        self.binary_directory("Bin/retail-backup", self.known["steam"])
        with self.assertRaisesRegex(BridgeError, "No retail WHGame.dll matches"):
            builders.inspect_game(self.game)

    def test_supported_development_folder_does_not_replace_missing_retail_executable(self):
        self.binary_directory("Bin/Win64MasterMaster", self.known["steam"])
        with self.assertRaisesRegex(BridgeError, "retail executable/DLL is missing"):
            builders.inspect_game(self.game)


if __name__ == "__main__":
    unittest.main()
