"""World coverage, terrain palette/holes and material conversion regressions."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from world_surface_scene import tile_origins
from world_surface_landscape import terrain_sector
from voxel_surfaces import load_surface,Surface,build_tile,diffuse_texture
from voxel_lighting import validate_pair
from world_voxels import configure_environment
import struct


class WorldSurfaceTests(unittest.TestCase):
    def test_surface_environment_keeps_authored_light_values(self):
        blob=b'<Mission><Environment><Total_Illumination_v2 SkyColorMultiplier="0.8" DiffuseAmplifier="1" /></Environment></Mission>'
        root=ET.fromstring(configure_environment(blob,surface_channels=True))
        settings=root.find('Environment/Total_Illumination_v2').attrib
        self.assertEqual(settings['IntegrationMode'],'1');self.assertEqual(settings['UseLightProbes'],'0')
        self.assertEqual(settings['UpdateLighting'],'1');self.assertEqual(settings['UpdateGeometry'],'0')
        self.assertEqual(settings['SkyColorMultiplier'],'0.8')
        legacy=ET.fromstring(configure_environment(blob)).find('Environment/Total_Illumination_v2')
        self.assertEqual(legacy.get('IntegrationMode'),'0')

    def test_conservative_bounds_can_produce_empty_tile(self):
        idx,vox,check=build_tile(np.empty((0,3,3)),np.empty((0,3,2)),np.empty(0,dtype=np.int32),[],
                                (0,0,0),allow_empty=True)
        self.assertEqual(check,validate_pair(idx,vox))
        self.assertEqual(check['nodes'],1);self.assertEqual(check['blocks'],0)

    def test_uncompressed_bgra_diffuse(self):
        blob=bytearray(128);blob[:4]=b'DDS '
        struct.pack_into('<7I',blob,4,124,0x100f,1,1,4,0,1)
        struct.pack_into('<8I',blob,76,32,65,0,32,0xff0000,0xff00,0xff,0xff000000)
        struct.pack_into('<I',blob,108,0x1000)
        class Assets:
            entries={}
            def get(self,name):return bytes(blob)+bytes([0,0,255,255])
        np.testing.assert_array_equal(diffuse_texture('red.dds',Assets()),[[[1,0,0,1]]])

    def test_crossing_tile_and_origin_boundaries(self):
        self.assertEqual(set(tile_origins([[255,1,1],[257,2,2]])),{(0,0,0),(256,0,0)})
        self.assertEqual(tile_origins([[-1,-1,-1],[1,1,1]]),[(0,0,0)])
        with self.assertRaises(ValueError):tile_origins([[float('nan'),0,0],[1,1,1]])

    def test_native_coverage_is_a_byte(self):
        for authored,expected in ((None,1),('0',0),('30',30/255),('255',1)):
            element=ET.Element('Material',Shader='Illum')
            if authored is not None:element.set('VoxelCoverage',authored)
            surface,_=load_surface(element,None,{})
            self.assertEqual(surface.coverage,expected)

    def test_clamped_texture_does_not_repeat_edges(self):
        s=Surface(np.array([[[1,0,0,1],[0,0,1,1]]]),[1,1,1],repeat=(False,False))
        rgb,_=s.sample([[-2,.5],[3,.5]])
        np.testing.assert_array_equal(rgb,[[1,0,0],[0,0,1]])

    def fixture(self,undefined=False):
        tags=np.array([[2,15,13],[6,14 if undefined else 2,13],[13,13,13]],dtype='<u4')
        packed=(np.arange(9,dtype='<u4').reshape(3,3)<<20)|tags
        terrain=SimpleNamespace(data=packed.tobytes()+bytes([10,20]))
        node={'size':3,'samples':0,'palette':36,'surface_count':2,
              'values':(8,1,0,0,0,2,2,5,10,.05,3,2)}
        surfaces={i:{'DetailMaterial':'layer'+str(i),'ProjectAxis':'2'} for i in (10,20)}
        return terrain,node,surfaces

    def test_sparse_terrain_palette_ignores_border_ids_and_preserves_hole(self):
        tri,uv,ids,bindings=terrain_sector(*self.fixture())
        self.assertEqual(len(tri),6)
        self.assertEqual(bindings,[['layer10',0],['layer20',0]])
        self.assertTrue((tri[:,:,2]>=10).all())
        self.assertTrue((np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])[:,2]>0).all())
        self.assertFalse(np.any((tri.mean(1)[:,0]<1)&(tri.mean(1)[:,1]>1)))

    def test_undefined_colour_requires_explicit_approximation(self):
        with self.assertRaisesRegex(ValueError,'Undefined terrain'):terrain_sector(*self.fixture(True))
        tri,_,_,_=terrain_sector(*self.fixture(True),approximate_undefined=True)
        self.assertEqual(len(tri),6)


if __name__=='__main__':unittest.main()
