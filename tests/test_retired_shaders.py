import sys
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from retired_shaders import (NATIVE_BEAM, drop_undeclared_features, native_beam_material,
                             replace_retired_beam, target_features)

ILLUM_EXT = '''Property { Name = %NORMAL_MAP Mask = 0x1 }
Property { Name = %SPECULAR_MAP Mask = 0x2 }
Property { Name = %SUBSURFACE_SCATTERING Mask = 0x4 }'''
NATIVE = ('<Material Shader="Illum" GenMask="24000000000000" StringGenMask="%SPECULAR_MAP%SUBSURFACE_SCATTERING" '
          'MtlFlags="524288" Diffuse="0.2,0.2,0.2" Specular="0,0,0" Shininess="10" Opacity="1">'
          '<Textures><Texture Map="Diffuse" File="./lightshafts_diff.tif"/></Textures>'
          '<PublicParams SSSIndex="0" EmittanceMapGamma="1"/></Material>')


def fake_library(root):
    (root / 'KingdomComeDeliverance2/Engine').mkdir(parents=True)
    (root / 'KingdomComeDeliverance2/Data').mkdir(parents=True)
    with zipfile.ZipFile(root / 'KingdomComeDeliverance2/Engine/Shaders.pak', 'w') as z:
        z.writestr('Shaders/Illum.ext', ILLUM_EXT)
    with zipfile.ZipFile(root / 'KingdomComeDeliverance2/Data/IPL_Objects-part1.pak', 'w') as z:
        z.writestr('Objects/manmade/common_illumination/lightshafts/lightshafts.mtl', NATIVE)
    (root / 'KingdomComeDeliverance2/Data/broken.pak').write_bytes(b'not a zip')
    return root


class RetiredShaderTests(unittest.TestCase):
    def test_undeclared_flags_are_dropped_and_declared_ones_kept(self):
        features = {'illum': {'%NORMAL_MAP': 1, '%SUBSURFACE_SCATTERING': 4}}
        element = ET.fromstring('<Material Shader="Illum" StringGenMask="%ALLOW_SILHOUETTE_POM%BUMP_MAP%SUBSURFACE_SCATTERING"/>')
        self.assertEqual(drop_undeclared_features(element, features), ['%ALLOW_SILHOUETTE_POM', '%BUMP_MAP'])
        self.assertEqual(element.get('StringGenMask'), '%SUBSURFACE_SCATTERING')

    def test_shaders_without_definitions_and_clean_masks_are_untouched(self):
        features = {'illum': {'%NORMAL_MAP': 1}}
        nodraw = ET.fromstring('<Material Shader="Nodraw" StringGenMask="%ANYTHING"/>')
        clean = ET.fromstring('<Material Shader="Illum" StringGenMask="%NORMAL_MAP"/>')
        self.assertEqual(drop_undeclared_features(nodraw, features), [])
        self.assertEqual(drop_undeclared_features(clean, features), [])
        self.assertEqual(nodraw.get('StringGenMask'), '%ANYTHING')
        self.assertEqual(clean.get('StringGenMask'), '%NORMAL_MAP')

    def test_geometry_beam_adopts_native_contract_and_keeps_source_textures(self):
        element = ET.fromstring(
            '<Material MtlFlags="524288" Shader="Geometrybeam" StringGenMask="" SurfaceType="mat_default" Diffuse="1,1,1">'
            '<Textures><Texture Map="Diffuse" File="t1_lightshafts_diff.dds"/>'
            '<Texture Map="Specular" File="t2_dust_diff.dds"/></Textures>'
            '<PublicParams dustUVScale="50" turbStrength="4"/></Material>')
        self.assertTrue(replace_retired_beam(element, ET.fromstring(NATIVE)))
        self.assertEqual(element.get('Shader'), 'Illum')
        self.assertEqual(element.get('StringGenMask'), '%SPECULAR_MAP%SUBSURFACE_SCATTERING')
        self.assertEqual(element.get('GenMask'), '24000000000000')
        self.assertEqual(element.get('Diffuse'), '0.2,0.2,0.2')
        self.assertEqual(element.get('SurfaceType'), 'mat_default')
        self.assertEqual([t.get('File') for t in element.iter('Texture')], ['t1_lightshafts_diff.dds', 't2_dust_diff.dds'])
        self.assertEqual(element.find('PublicParams').attrib, {'SSSIndex': '0', 'EmittanceMapGamma': '1'})

    def test_other_shaders_are_not_replaced(self):
        element = ET.fromstring('<Material Shader="Illum" Diffuse="1,1,1"/>')
        self.assertFalse(replace_retired_beam(element, ET.fromstring(NATIVE)))
        self.assertEqual(element.get('Diffuse'), '1,1,1')

    def test_native_beam_that_is_still_a_beam_is_rejected(self):
        element = ET.fromstring('<Material Shader="Geometrybeam"/>')
        with self.assertRaises(ValueError):
            replace_retired_beam(element, ET.fromstring('<Material Shader="GeometryBeam"/>'))

    def test_contracts_are_read_from_the_installed_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = fake_library(Path(tmp))
            features = target_features(library)
            self.assertEqual(features['illum']['%SPECULAR_MAP'], 2)
            native = ET.fromstring(native_beam_material(library))
            self.assertEqual(native.get('Shader'), 'Illum')
            self.assertTrue(NATIVE_BEAM.endswith('lightshafts.mtl'))

    def test_missing_native_material_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'KingdomComeDeliverance2/Data').mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                native_beam_material(root)


if __name__ == '__main__':
    unittest.main()
