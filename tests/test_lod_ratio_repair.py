import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_lod_ratio_metadata import fixture
from lod_ratio_metadata import MARKER, convert, marker_for, upgrade_package, validate_marker
from lod_ratio_repair import mark_geometry_edit
from setup_package_upgrade import rewrite
from setup_section_repair import repair, stale_sections
from setup_campaign import MOD_ID, RECEIPT, digest, verify_package
from setup_resume import update_private_package
from world_brush_edits import edit


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root/'saved'/'package'/'map'
        self.package = self.root/'current'
        self.relative = 'Data/Levels/kcd1_travel/level.pak'
        terrain, raw = fixture()
        raw = bytearray(raw)
        self.brush = 200
        struct.pack_into('<6f', raw, self.brush+4, 0,1,2,2,3,4)
        struct.pack_into('<12f', raw, self.brush+44, 1,0,0,1,0,1,0,2,0,0,1,3)
        self.terrain, self.original, report = convert(terrain, bytes(raw))
        self.marker = marker_for(self.terrain, self.original, report)
        self.metadata = (f'<HLod DataOffset="4" DataSize="{len(raw)-4}" '
                         'Pos="0,0,0" Radius="10000"/>').encode()
        self.edits = (dict(position=(1,2,3), bbox=(0,1,2,2,3,4), delta=(.25,0,0)),)
        self.current, metadata = edit(self.original, self.metadata, self.edits)
        self.write_package(self.reference, self.original, self.metadata)
        self.write_package(self.package, self.current, metadata)
        self.addCleanup(patch.stopall)
        patch('forge_loft.BRUSH_EDITS', self.edits).start()

    def write_package(self, package, hlod, metadata):
        level = package/'Data/Levels/kcd1_travel'
        level.mkdir(parents=True)
        for name, entries in (
            ('level.pak', {'terrain/hlods.dat':hlod, 'terrain/hlods.xml':metadata,
                           MARKER:json.dumps(self.marker).encode(), 'quests.bin':b'keep quests'}),
            ('terrain.pak', {'terrain/terrain.dat':self.terrain, 'baked.bin':b'keep lighting'})):
            with zipfile.ZipFile(level/name, 'w') as archive:
                for entry, blob in entries.items(): archive.writestr(entry, blob)

    def receipt(self):
        (self.package/'mod.manifest').write_text(f'<root><info><modid>{MOD_ID}</modid></info></root>')
        (self.package/'campaign-audit.json').write_text('{}')
        (self.package/'Data'/f'{MOD_ID}.pak').write_bytes(b'unchanged runtime')
        files = {p.relative_to(self.package).as_posix():digest(p)
                 for p in self.package.rglob('*') if p.is_file()}
        value = dict(schema=1, owner=MOD_ID, files=files, custom_state={'quests':'preserve'})
        (self.package/RECEIPT).write_text(json.dumps(value))
        return value

    def test_geometry_only_staleness_repairs_marker_and_nothing_else(self):
        original = self.receipt()
        self.assertEqual(stale_sections(self.package), ['lod_ratios'])
        update_private_package(self.package, lambda p:repair(p, repair_roots=(self.root,)), lambda:False)
        after = verify_package(self.package)
        self.assertEqual([k for k in original['files'] if original['files'][k]!=after['files'][k]],
                         [self.relative])
        self.assertEqual(after['custom_state'], original['custom_state'])
        self.assertEqual(after['section_repairs']['lod_ratios']['repaired_ratio_bytes'], 0)
        with zipfile.ZipFile(self.package/self.relative) as z:
            self.assertEqual(z.read('terrain/hlods.dat'), self.current)
            self.assertEqual(z.read('quests.bin'), b'keep quests')
        self.assertEqual(stale_sections(self.package), [])
        before = (self.package/RECEIPT).read_bytes()
        repair(self.package, repair_roots=(self.root,))
        self.assertEqual((self.package/RECEIPT).read_bytes(), before)
        self.assertEqual(upgrade_package(self.package)[0], {})

    def test_recovers_actual_ratio_damage_without_double_encoding(self):
        damaged = bytearray(self.current)
        damaged[self.brush+43] = 200  # unconverted byte mixed into finalized data
        rewrite(self.package, self.relative, {'terrain/hlods.dat':bytes(damaged)})
        files, report = upgrade_package(self.package, repair_roots=(self.root,))
        self.assertEqual(set(files), {self.relative})
        self.assertEqual(report['recovery']['repaired_ratio_bytes'], 1)
        with zipfile.ZipFile(self.package/self.relative) as z:
            self.assertEqual(z.read('terrain/hlods.dat'), self.current)
        self.assertEqual(upgrade_package(self.package)[0], {})

    def test_unknown_geometry_native_damage_or_missing_evidence_fails_without_writes(self):
        for index in (self.brush+50, 304+43):
            bad = bytearray(self.current); bad[index] ^= 1
            rewrite(self.package, self.relative, {'terrain/hlods.dat':bytes(bad)})
            before = (self.package/self.relative).read_bytes()
            with self.assertRaisesRegex(ValueError, 'no verified saved'):
                upgrade_package(self.package, repair_roots=(self.root,))
            self.assertEqual((self.package/self.relative).read_bytes(), before)
        rewrite(self.package, self.relative, {'terrain/hlods.dat':self.current})
        with self.assertRaisesRegex(ValueError, 'no verified saved'):
            upgrade_package(self.package, repair_roots=(self.root/'absent',))
        with self.assertRaisesRegex(ValueError, 'marker does not match'):
            upgrade_package(self.package, repair_roots=(self.root,), validate_only=True)

    def test_stale_reference_is_not_trusted(self):
        bad = bytearray(self.original);bad[51] ^= 1
        rewrite(self.reference, self.relative, {'terrain/hlods.dat':bytes(bad)})
        with self.assertRaisesRegex(ValueError, 'no verified saved'):
            upgrade_package(self.package, repair_roots=(self.root,))

    def test_changed_group_ratios_are_restored_from_verified_reference(self):
        from compiled_terrain import parse
        bad = bytearray(self.terrain)
        offset = parse(self.terrain).tables['vegetation']['offset']+324
        struct.pack_into('<f', bad, offset, 2.55)
        rewrite(self.package, self.relative.replace('level.pak','terrain.pak'), {'terrain/terrain.dat':bytes(bad)})
        files, report = upgrade_package(self.package, repair_roots=(self.root,))
        self.assertEqual(len(files), 2)
        self.assertEqual(report['recovery']['repaired_group_ratios'], 1)
        with zipfile.ZipFile(self.package/self.relative.replace('level.pak','terrain.pak')) as archive:
            self.assertEqual(archive.read('terrain/terrain.dat'), self.terrain)
            self.assertEqual(archive.read('baked.bin'), b'keep lighting')

    def test_failed_or_cancelled_repair_keeps_receipt_and_hardlinked_baseline(self):
        self.receipt()
        before = {p.relative_to(self.package):p.read_bytes() for p in self.package.rglob('*') if p.is_file()}
        late_cancel = iter((False, True))
        for roots, cancel in (((self.root/'missing',),lambda:False), ((self.root,),lambda:True),
                              ((self.root,),lambda:next(late_cancel))):
            with self.assertRaises((ValueError, InterruptedError)):
                update_private_package(self.package,
                    lambda p:repair(p, repair_roots=roots, cancelled=cancel), lambda:False)
            self.assertEqual(before, {p.relative_to(self.package):p.read_bytes() for p in self.package.rglob('*') if p.is_file()})

    def test_new_registered_geometry_edits_keep_marker_current(self):
        marker = mark_geometry_edit(self.terrain, self.original, self.current,
                                    self.metadata, self.marker, self.edits)
        validate_marker(self.terrain, self.current, marker)
        bad = bytearray(self.current);bad[self.brush+43] ^= 1
        with self.assertRaisesRegex(ValueError, 'outside its registered edits'):
            mark_geometry_edit(self.terrain, self.original, bytes(bad), self.metadata, self.marker, self.edits)


if __name__ == '__main__': unittest.main()
