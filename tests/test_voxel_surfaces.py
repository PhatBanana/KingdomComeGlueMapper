"""Analytical material, coverage and binary-format checks for offline GI."""
from pathlib import Path
import struct
import sys
import unittest
import zlib
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from voxel_surfaces import Surface, srgb_to_linear, rasterize, encode_brick, build_tile, diffuse_texture
from voxel_lighting import validate_pair, RECORD
from test_geometry_opacity import quad


class SurfaceTests(unittest.TestCase):
    def test_parallel_bricks_preserve_serial_file_bytes(self):
        rng=np.random.default_rng(91)
        t=rng.uniform(0,16,(90,3,3));u=rng.uniform(-1,2,(90,3,2));ids=np.zeros(90,dtype=int)
        m=[Surface(rng.random((3,4,4)).astype(np.float32),[.8,.7,.6],alpha_test=.4)]
        serial=build_tile(t,u,ids,m,(0,0,0),16,8,backend='compiled')
        for workers in (2,4):self.assertEqual(serial[:2],build_tile(t,u,ids,m,(0,0,0),16,8,backend='compiled',workers=workers)[:2])

    def test_compiled_matches_reference_with_alpha_and_crossing_geometry(self):
        try:
            from voxel_raster_fast import prepare, rasterize as fast
        except ImportError:
            self.skipTest('optional numba backend not installed')
        rng=np.random.default_rng(814)
        triangles=rng.uniform(-1,5,(25,3,3));uv=rng.uniform(-2,2,(25,3,2))
        materials=[Surface(rng.random((3,4,4)),[.8,.4,.2],alpha_test=.4),
                   Surface(rng.random((2,3,4)),[.1,.2,.9],opacity=.7,coverage=.6,tile=(2,3),offset=(-.1,.2))]
        ids=rng.integers(0,2,25)
        for samples in (1,2,4):
            reference=rasterize(triangles,uv,ids,materials,(0,0,0),(4,4,4),1,samples)
            compiled=fast(triangles,uv,ids,prepare(materials),(0,0,0),(4,4,4),1,samples)
            for key in reference:np.testing.assert_allclose(compiled[key],reference[key],atol=2e-7)

    def test_neighbor_tiles_retain_crossing_surface(self):
        triangles=quad(7,9,1,3,.5);uv=np.zeros((2,3,2));ids=np.zeros(2,dtype=int)
        materials=[Surface(np.ones((1,1,4)),[1,0,0])]
        for origin in ((0,0,0),(8,0,0)):
            _,_,report=build_tile(triangles,uv,ids,materials,origin,8,8)
            self.assertEqual(report['blocks'],1)

    def scene(self, material=None, triangles=None, samples=4):
        tris=quad(0,1,0,1,.5) if triangles is None else triangles
        uv=np.array([[[0,0],[1,0],[1,1]],[[0,0],[1,1],[0,1]]],float)
        return rasterize(tris,uv,np.zeros(2,dtype=int),[material or Surface(np.ones((1,1,4)),[.8,.2,.1])],(0,0,0),(1,1,1),1,samples)

    def test_coloured_plane_and_normal(self):
        f=self.scene()
        np.testing.assert_allclose(f['opacity'][0,0,0],[0,0,1])
        np.testing.assert_allclose(f['albedo'][0,0,0],[.8,.2,.1])
        np.testing.assert_allclose(f['normals'][0,0,0],[0,0,1])

    def test_alpha_cutout_and_uv_sampling(self):
        rgba=np.ones((1,2,4));rgba[0,0,3]=0
        f=self.scene(Surface(rgba,[1,1,1],alpha_test=.5),samples=8)
        self.assertGreater(f['opacity'][0,0,0,2],0)
        self.assertLess(f['opacity'][0,0,0,2],.5)
        np.testing.assert_allclose(f['albedo'][0,0,0],[1,1,1])
        self.assertFalse(self.scene(Surface(np.zeros((1,1,4)),[1,1,1]))['opacity'].any())

    def test_coverage_zero_does_not_occlude(self):
        f=self.scene(Surface(np.ones((1,1,4)),[1,1,1],coverage=0))
        for a in f.values():self.assertFalse(a.any())

    def test_duplicate_triangles_do_not_add_energy(self):
        tri=quad(0,1,0,1,.5);uv=np.array([[[0,0],[1,0],[1,1]],[[0,0],[1,1],[0,1]]])
        f=rasterize(np.concatenate([tri,tri]),np.concatenate([uv,uv]),np.zeros(4,dtype=int),
            [Surface(np.ones((1,1,4)),[.8,.2,.1])],(0,0,0),(1,1,1),1)
        for k,v in self.scene().items():np.testing.assert_allclose(f[k],v)

    def test_winding_and_tilt(self):
        f=self.scene(triangles=quad(0,1,0,1,.5)[:,::-1])
        np.testing.assert_allclose(f['normals'][0,0,0],[0,0,-1])
        t=quad(0,1,0,1,0);t[:,:,2]=t[:,:,0]*.5+.1
        np.testing.assert_allclose(self.scene(triangles=t)['normals'][0,0,0],np.array([-.5,0,1])/np.sqrt(1.25))

    def test_bilinear_repeat_and_linear_filter(self):
        tex=np.array([[[0,0,0,1],[1,1,1,1]]],float)
        s=Surface(tex,[1,1,1])
        rgb,_=s.sample(np.array([[0,.5],[1,.5],[-1,.5],[.5,.5]]))
        np.testing.assert_allclose(rgb,.5)
        np.testing.assert_allclose(srgb_to_linear([0,.5,1]),[0,.21404114,1],rtol=1e-6)

    def test_binary_channel_order_and_normal_encoding(self):
        f={k:np.zeros((16,16,16,3)) for k in ('opacity','albedo','normals')}
        f['opacity'][3,2,1]=[.2,.4,1];f['albedo'][3,2,1]=[1,.2,.4];f['normals'][3,2,1]=[0,0,1]
        b=encode_brick(f);self.assertEqual(struct.unpack_from('<II',b,12),(7,255))
        a=np.frombuffer(b[20:],np.uint8).reshape(3,16,16,16,4)
        np.testing.assert_array_equal(a[0,3,2,1],[255,102,51,255])
        np.testing.assert_array_equal(a[1,3,2,1],[102,51,255,0])
        np.testing.assert_array_equal(a[2,3,2,1],[255,127,127,255])

    def test_octree_payload_and_world_position(self):
        t=quad(10,12,20,22,30.5);uv=np.zeros((2,3,2))
        idx,vox,report=build_tile(t,uv,np.zeros(2,dtype=int),[Surface(np.ones((1,1,4)),[1,0,0])],(0,0,0),64,8)
        self.assertEqual(report['channel_masks'],[7]);self.assertGreater(report['blocks'],1)
        self.assertEqual(report,validate_pair(idx,vox))
        for x,y,z,e,_,_,off,n in RECORD.iter_unpack(idx[4:]):
            if off==0xffffffff:continue
            raw=zlib.decompress(vox[off+4:off+n]);a=np.frombuffer(raw[20:],np.uint8).reshape(3,16,16,16,4)
            for iz,iy,ix in np.argwhere(a[0,...,0]>0):
                self.assertLessEqual(z+iz*e/16,30.5)
                self.assertGreater(z+(iz+1)*e/16,30.5)

    def test_missing_uv_and_invalid_grid_rejected(self):
        with self.assertRaises(ValueError):rasterize(quad(0,1,0,1,.5),np.zeros((2,3,2)),np.zeros(2,dtype=int),[],(0,0,0),(1,1,1),1)
        with self.assertRaises(ValueError):self.scene(Surface(np.ones((1,1,4)),[1,1,1]),samples=3)

    def test_split_dds_top_mip_is_not_missing_texture_substitution(self):
        # BC1 opaque red, top 8x8 mip split from 4x4 tail. DXGI sRGB alias.
        b=bytearray(148);b[:4]=b'DDS ';struct.pack_into('<I',b,4,124)
        struct.pack_into('<II',b,12,8,8);struct.pack_into('<I',b,28,2)
        struct.pack_into('<II',b,76,32,4);b[84:88]=b'DX10';struct.pack_into('<5I',b,128,72,3,0,1,0)
        block=struct.pack('<HHI',0xf800,0,0)
        class Assets:
            entries={'test.dds.1':True}
            def get(self,n):return bytes(b)+block if n=='test.dds' else block*4
        rgba=diffuse_texture('test.dds',Assets())
        np.testing.assert_allclose(rgba[0,0],[1,0,0,1]);self.assertEqual(rgba.shape,(8,8,4))
        Assets.entries={}
        with self.assertRaises(ValueError):diffuse_texture('test.dds',Assets())

if __name__=='__main__':unittest.main()
