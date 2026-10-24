import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clothing_zone_upgrade import apply, fresh_report, packaged, upgrade, VERSION
from npc_effects import bake_macro_diffuse, read_dds_family, write_float_dds

NAMESPACE = 'gm_person_0123456789abcdef0123456789abcdef'
FOLDER = 'objects/characters/gluetravel/' + NAMESPACE + '/'
LEGACY = ('<Material Shader="Illum" StringGenMask="%COLORIZING%COLORIZING_WITH_MASK%SPECULAR_MAP"><Textures>'
          f'<Texture Map="Diffuse" File="{FOLDER}t1_diff.dds"/><Texture Map="Specular" File="{FOLDER}t2_spec.dds"/>'
          '</Textures><PublicParams MaskBrightness2="0.5" MaskBrightness3="1"/></Material>')
NATIVE = ('<Material Shader="Illum" StringGenMask="%CLOTHING_SYSTEM"><SubMaterials>' + ''.join(
          f'<Material StringGenMask="%CLOTHING_SYSTEM"><Textures><Texture Map="Diffuse" File="{FOLDER}{n}"/>'
          '</Textures></Material>' for n in ('native_outfit_legs_0_diff.dds', 'native_outfit_feet_0_diff.dds'))
          + '</SubMaterials></Material>')


def srgb_mask():
    """4x4 BC1_UNORM_SRGB whose green (6-bit 51, about 206) is zone 3 encoded, zone 2 decoded."""
    header = bytearray(148); header[:4] = b'DDS '
    struct.pack_into('<7I', header, 4, 124, 0x81007, 4, 4, 8, 0, 1)
    struct.pack_into('<2I4s', header, 76, 32, 4, b'DX10'); struct.pack_into('<I', header, 108, 0x1000)
    struct.pack_into('<5I', header, 128, 72, 3, 0, 1, 0)
    return bytes(header) + struct.pack('<HHI', 51 << 5, 51 << 5, 0)


class ClothingZoneUpgradeTests(unittest.TestCase):
    def package(self, root):
        work = root / 'work'; work.mkdir()
        Image.new('RGBA', (4, 4), (180, 120, 90, 255)).save(work / 'diff.dds')
        (work / 'spec.dds').write_bytes(srgb_mask())
        diffuse, spec = read_dds_family(work / 'diff.dds'), read_dds_family(work / 'spec.dds')

        def baked(decoded):
            mask = spec.copy(); mask.info['srgb'] = decoded
            write_float_dds(work / 'bake.dds', bake_macro_diffuse(diffuse, ET.fromstring(LEGACY), mask))
            return (work / 'bake.dds').read_bytes()
        self.old, self.new = baked(False), baked(True)
        self.assertNotEqual(self.old, self.new)
        # A native texture that no legacy material in the person reproduces.
        self.other = self.old[:148] + bytes(len(self.old) - 148)
        legs = FOLDER + 'native_outfit_legs_0_diff.dds'
        members = {FOLDER + 't1_diff.dds': (work / 'diff.dds').read_bytes(), FOLDER + 't2_spec.dds': srgb_mask(),
                   FOLDER + 'part0_tinted.mtl': LEGACY.encode(), FOLDER + 'outfit_legs.mtl': NATIVE.encode(),
                   **{legs + s: b for s, b in packaged(legs, self.old).items()},
                   FOLDER + 'native_outfit_feet_0_diff.dds': self.other}
        (root / 'Data').mkdir()
        pak = root / 'Data' / (NAMESPACE + '.pak')
        with zipfile.ZipFile(pak, 'w', zipfile.ZIP_STORED) as archive:
            for name, blob in members.items(): archive.writestr(name, blob)
        return pak

    def test_reproduced_texture_is_rebaked_with_decoded_zones(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'package'; root.mkdir()
            pak = self.package(root)
            changed, report = upgrade(root)
            self.assertEqual(list(changed), ['Data/' + pak.name])
            self.assertEqual([t['source'] for t in report['textures']], [FOLDER + 'part0_tinted.mtl'])
            with zipfile.ZipFile(pak) as archive:
                self.assertEqual(archive.read(FOLDER + 'native_outfit_legs_0_diff.dds'), self.new)
                self.assertEqual(archive.read(FOLDER + 'native_outfit_feet_0_diff.dds'), self.other)
            # Repeat runs change nothing: the fixed bake no longer reproduces from old code.
            changed, report = upgrade(root)
            self.assertEqual(changed, {}); self.assertEqual(report['textures'], [])

    def test_apply_runs_once_and_fresh_builds_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'package'; root.mkdir()
            pak = self.package(root)
            receipt = dict(files={})
            apply(root, receipt)
            self.assertEqual(receipt['clothing_zone_mask']['version'], VERSION)
            self.assertIn('Data/' + pak.name, receipt['files'])
            before = pak.read_bytes()
            fresh = dict(files={}, clothing_zone_mask=fresh_report())
            apply(root, fresh); apply(root, receipt)
            self.assertEqual(fresh['files'], {}); self.assertEqual(pak.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
