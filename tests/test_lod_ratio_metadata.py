import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from compiled_terrain import parse
from lod_ratio_metadata import (MARKER, convert, decode_target_ratio,
    encode_source_ratio, group_byte, group_ratio, upgrade_package)


def fixture():
    header = bytearray(32)
    struct.pack_into('<4BIIfII', header, 0, 29, 0, 6, 0, 0, 4096, 1, 64, 64)
    groups = bytearray()
    for path, ratio in [('glueveg/tree.cgf', 2.55), ('objects/native/tree.cgf', 1.3),
                        ('glueveg/merged.cgf', 100), ('glueveg/bush.cgf', 1.6)]:
        row = bytearray(360)
        row[:256] = path.encode().ljust(256, b'\0')
        struct.pack_into('<f', row, 324, ratio)
        groups.extend(row)
    meshes = b'gluebuild/roof.cgf'.ljust(256, b'\0') + b'objects/native/roof.cgf'.ljust(256,b'\0')
    terrain = header + struct.pack('<I',4) + groups + struct.pack('<I',2) + meshes + bytes(4)
    terrain += (struct.pack('<hh8fii',8,0,*([0.0]*8),0,0)+bytes(24))*5461
    terrain += struct.pack('<HBB6fI',8,0,0,0,0,0,4096,4096,4096,0)
    struct.pack_into('<I',terrain,4,len(terrain))
    items = []
    for kind, resource, ratio in [(2,0,255),(2,1,130),(2,3,160),(1,0,200),(1,1,255)]:
        row = bytearray(range(64 if kind == 2 else 104))
        struct.pack_into('<I',row,0,kind)
        struct.pack_into('<H',row,40,resource)
        row[43] = ratio
        items.append(bytes(row))
    payload = b''.join(items)
    return bytes(terrain), struct.pack('<II',2,len(payload))+payload


class LodRatioTests(unittest.TestCase):
    def test_preserves_source_meaning_in_observed_kcd2_nonlinear_encoding(self):
        self.assertEqual(encode_source_ratio(255),113)
        self.assertEqual(encode_source_ratio(160),105)
        self.assertEqual(encode_source_ratio(200),108)
        self.assertEqual(decode_target_ratio(255),20)
        for source in range(256):
            target = encode_source_ratio(source)
            if source <= 100:
                self.assertEqual(target,source)
            # At most half of one KCD2 quantization step.
            self.assertLessEqual(abs(decode_target_ratio(target)-source/100),19/310+1e-12)
        for invalid in [-1,256,1.5]:
            with self.assertRaises(ValueError): encode_source_ratio(invalid)

    def test_group_float_roundtrips_native_float32_multiply_and_truncate(self):
        for value in range(256):
            self.assertEqual(group_byte(group_ratio(value)),value)
        self.assertEqual(group_byte(100.0),255)  # source saturated at 255
        for value in [-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError): group_byte(value)

    def test_changes_only_imported_lod_bytes_and_group_ratios(self):
        terrain, hlod = fixture()
        new_terrain, new_hlod, report = convert(terrain,hlod)
        self.assertEqual(report['changed'],{'vegetation':2,'brushes':1,'groups':3})
        self.assertEqual([i for i,(a,b) in enumerate(zip(hlod,new_hlod)) if a!=b],
                         [8+43,8+128+43,8+192+43])
        self.assertEqual([new_hlod[i] for i in [51,115,179,243,347]],[113,130,105,108,255])
        table=parse(terrain).tables['vegetation']['offset']
        allowed={table+g*360+324+j for g in [0,2,3] for j in range(4)}
        self.assertTrue(all(i in allowed for i,(a,b) in enumerate(zip(terrain,new_terrain)) if a!=b))
        # The imported shadow/physics flags, transforms and canopy bounds stay byte-identical.
        self.assertEqual(len(new_hlod),len(hlod))
        self.assertEqual(len(new_terrain),len(terrain))

    def test_malformed_blocks_and_resource_references_are_rejected(self):
        terrain, hlod = fixture()
        for bad in [hlod[:-1],b'\0'*4,hlod+b'x']:
            with self.assertRaises(ValueError): convert(terrain,bad)
        bad=bytearray(hlod);struct.pack_into('<H',bad,8+40,999)
        with self.assertRaisesRegex(ValueError,'resource index'):convert(terrain,bad)

    def test_clean_and_resume_use_same_stage_and_never_double_convert(self):
        terrain, hlod=fixture()
        with tempfile.TemporaryDirectory() as directory:
            package=Path(directory);level=package/'Data/Levels/kcd1_travel';level.mkdir(parents=True)
            for name,entries in [('terrain.pak',{'terrain/terrain.dat':terrain,'baked.bin':b'baked lighting'}),
                                 ('level.pak',{'terrain/hlods.dat':hlod,'terrain/hlods.xml':b'hierarchy',
                                               'objects_mission0.xml':b'quests, collision, entities'})]:
                with zipfile.ZipFile(level/name,'w') as archive:
                    for key,payload in entries.items():archive.writestr(key,payload)
            with self.assertRaisesRegex(ValueError,'missing.*encoding'):upgrade_package(package,validate_only=True)
            files, report=upgrade_package(package)
            self.assertEqual(len(files),2)
            first={p.name:p.read_bytes() for p in level.iterdir()}
            for _ in range(2):
                files,current=upgrade_package(package)
                self.assertEqual(files,{})
                self.assertTrue(current['already_current'])
                upgrade_package(package,validate_only=True)
            self.assertEqual(first,{p.name:p.read_bytes() for p in level.iterdir()})
            with zipfile.ZipFile(level/'level.pak') as archive:
                self.assertEqual(archive.read('objects_mission0.xml'),b'quests, collision, entities')
                self.assertEqual(archive.read('terrain/hlods.xml'),b'hierarchy')
                self.assertEqual(json.loads(archive.read(MARKER))['transitions'],report['transitions'])
            with zipfile.ZipFile(level/'terrain.pak') as archive:
                self.assertEqual(archive.read('baked.bin'),b'baked lighting')
            # A stale marker must not cause a partial/second encoding after resume.
            from setup_package_upgrade import rewrite
            rewrite(package,'Data/Levels/kcd1_travel/level.pak',{'terrain/hlods.dat':hlod})
            with self.assertRaisesRegex(ValueError,'marker does not match'):upgrade_package(package)


if __name__ == '__main__': unittest.main()
