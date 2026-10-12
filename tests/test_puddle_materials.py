import sys
from pathlib import Path
import unittest
import tempfile
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from puddle_materials import convert_puddle_proxies
from build_puddle_surface_patch import stage


def puddle():
    return ET.fromstring('''<Material MtlFlags="524544"><SubMaterials>
      <Material Name="soil" Shader="Illum" SurfaceType="mat_mudwater"
        StringGenMask="%DECAL%NORMAL_MAP" CustomSortPriority="40"><Textures>
        <Texture Map="Diffuse" File="glue/t1803_puddle_4_diff.dds"/>
        <Texture Map="Bumpmap" File="glue/t1804_puddle_4_ddna.dds"/>
      </Textures></Material>
      <Material Name="proxy" Shader="Nodraw" MtlFlags="525440" SurfaceType="mat_water"/>
    </SubMaterials></Material>''')


class PuddleMaterials(unittest.TestCase):
    def test_only_proxy_surface_changes_and_repeat_is_noop(self):
        doc = puddle()
        expected = puddle()
        expected.find("SubMaterials/Material[@Name='proxy']").set('SurfaceType', 'mat_mudwater')
        self.assertEqual(convert_puddle_proxies(doc), 1)
        self.assertEqual(ET.tostring(doc), ET.tostring(expected))
        self.assertEqual(convert_puddle_proxies(doc), 0)
        self.assertEqual(ET.tostring(doc), ET.tostring(expected))

    def test_water_and_nonpuddle_materials_are_preserved(self):
        for attribute, value in [('Shader', 'WaterVolume'), ('SurfaceType', 'mat_water'),
                                 ('StringGenMask', '%DECAL_MAP%NORMAL_MAP')]:
            with self.subTest(attribute=attribute):
                doc = puddle()
                doc.find('SubMaterials/Material').set(attribute, value)
                before = ET.tostring(doc)
                self.assertEqual(convert_puddle_proxies(doc), 0)
                self.assertEqual(ET.tostring(doc), before)
        doc = puddle()
        doc.find('SubMaterials/Material/Textures/Texture').set('File', 'soil_diff.dds')
        self.assertEqual(convert_puddle_proxies(doc), 0)

    def test_mixed_water_material_not_reclassified(self):
        doc = puddle()
        ET.SubElement(doc.find('SubMaterials'), 'Material', Shader='Water', SurfaceType='mat_water')
        before = ET.tostring(doc)
        self.assertEqual(convert_puddle_proxies(doc), 0)
        self.assertEqual(ET.tostring(doc), before)

    def test_package_patch_preserves_other_payloads_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            untouched = {'texture.dds': bytes(range(256)) * 128,
                         'water.mtl': b'<Material Shader="Water" SurfaceType="mat_water"/>'}
            with zipfile.ZipFile(source / 'world.pak', 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('puddle.mtl', ET.tostring(puddle()))
                for name, payload in untouched.items():
                    z.writestr(name, payload)
            result = stage(source, root / 'first')
            self.assertEqual(len(result), 1)
            with zipfile.ZipFile(root / 'first/world.pak') as z:
                for name, payload in untouched.items():
                    self.assertEqual(z.read(name), payload)
                converted = ET.fromstring(z.read('puddle.mtl'))
                self.assertEqual(convert_puddle_proxies(converted), 0)
            self.assertEqual(stage(root / 'first', root / 'second'), [])


if __name__ == '__main__':
    unittest.main()
