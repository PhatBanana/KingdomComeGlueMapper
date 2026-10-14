import sys
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from world_surface_coverage import transforms,vegetation_group,gi_mode,HeightField

class CoverageTests(unittest.TestCase):
    def test_authored_group_gi_and_material(self):
        blob=bytearray(360);struct.pack_into('<f',blob,280,.5);struct.pack_into('<I',blob,332,256);struct.pack_into('<i',blob,336,0)
        t=SimpleNamespace(data=blob,tables={'vegetation':{'paths':['tree.cgf'],'offset':0},'materials':{'paths':['leaves']}})
        g=vegetation_group(t,0);self.assertTrue(g['gi_enabled']);self.assertEqual(g['material'],'leaves');self.assertEqual(g['alignment'],.5)
        struct.pack_into('<I',blob,332,0);self.assertFalse(vegetation_group(t,0)['gi_enabled'])
        with self.assertRaises(ValueError):vegetation_group(t,1)
        struct.pack_into('<i',blob,336,3)
        with self.assertRaises(ValueError):vegetation_group(t,0)

    def test_gi_mode_bit_positions(self):
        self.assertEqual(gi_mode((1<<10)|(1<<23)),5)
        self.assertEqual(gi_mode(1<<16),2)

    def test_transform_rotation_scale_and_translation(self):
        t=transforms([[10,20,30]],[2],[[0,0,255/4]])[0]
        np.testing.assert_allclose(t[:,:3]@np.array([1,0,0]),[0,2,0],atol=1e-14)
        np.testing.assert_array_equal(t[:,3],[10,20,30])
        full=transforms([[0,0,0]],[1],[[255,255,255]])[0]
        np.testing.assert_allclose(full[:,:3],np.eye(3),atol=1e-14)

    def test_terrain_alignment_uses_normal_and_yaw(self):
        normal=np.array([[0,-1,1.]])/np.sqrt(2)
        t=transforms([[0,0,0]],[1],[[123,47,0]],1,normal)[0,:,:3]
        np.testing.assert_allclose(t[:,2],normal[0]);np.testing.assert_allclose(t.T@t,np.eye(3),atol=1e-14)
        self.assertAlmostEqual(np.linalg.det(t),1.)
        flat=transforms([[0,0,0]],[1],[[123,47,0]],1,[[0,0,1]])[0,:,:3]
        np.testing.assert_allclose(flat,np.eye(3))
        with self.assertRaises(ValueError):transforms([[0,0,0]],[1],[[0,0,0]],1)

    def test_surface_normal_samples_bilinear_height(self):
        h=HeightField.__new__(HeightField)
        h.heights=np.broadcast_to(np.arange(4097)[:,None]*.5,(4097,4097))
        np.testing.assert_allclose(h.normal(np.array([[100.2,200.7,0],[4000,3000,1]])),np.tile(np.array([-.5,0,1])/np.sqrt(1.25),(2,1)),atol=1e-12)
        self.assertAlmostEqual(float(h.height(np.array([100.2]),np.array([200.7]))[0]),50.1)

if __name__=='__main__':unittest.main()
