import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from vegetation_materials import native_vine_deformation


class VineDeformation(unittest.TestCase):
    def test_native_motion_preserves_textures_and_is_idempotent(self):
        old = ET.fromstring('<Material Shader="Vegetation" AlphaTest="0.36"><Textures><Texture File="imported.dds"/></Textures><VertexDeform Type="1"><WaveX Amp="0.025"/></VertexDeform><PublicParams bendDetailFrequency="4" BackDiffuseMultiplier="4"/></Material>')
        native = ET.fromstring('<Material Shader="Vegetation" vertModifType="1"><VertexDeform DividerX="0.001" NoiseScale="0.1,0.1,0.1" Type="1"><WaveX Amp="0.0015" Freq="0.006"/></VertexDeform><PublicParams bendDetailFrequency="1"/></Material>')
        native_vine_deformation(old, native)
        first = ET.tostring(old)
        native_vine_deformation(old, native)
        self.assertEqual(ET.tostring(old), first)
        self.assertEqual(ET.tostring(old.find('VertexDeform')), ET.tostring(native.find('VertexDeform')))
        self.assertEqual(old.find('Textures/Texture').get('File'), 'imported.dds')
        self.assertEqual(old.get('AlphaTest'), '0.36')
        self.assertEqual(old.find('PublicParams').get('BackDiffuseMultiplier'), '4')
        self.assertEqual(old.find('PublicParams').get('bendDetailFrequency'), '1')
