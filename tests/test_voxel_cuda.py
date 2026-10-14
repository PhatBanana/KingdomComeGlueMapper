"""Optional hardware tests: build tools/build_voxel_cuda.ps1 before running."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from voxel_surfaces import Surface, build_tile
import voxel_raster_fast as cpu
import voxel_raster_cuda as gpu


@unittest.skipUnless((Path(__file__).resolve().parents[1]/'outputs/cuda/voxel_raster_cuda.dll').exists(),'optional CUDA DLL not built')
class CudaTests(unittest.TestCase):
    prepare=staticmethod(gpu.prepare)
    def test_ordered_overlap_cutouts_and_address_modes(self):
        rng=np.random.default_rng(814)
        t=rng.uniform(-1,5,(150,3,3));u=rng.uniform(-2,2,(150,3,2));ids=rng.integers(0,2,150)
        mats=[Surface(rng.random((3,4,4)),[.8,.4,.2],alpha_test=.4),
              Surface(rng.random((2,3,4)),[.1,.2,.9],opacity=.7,coverage=.6,tile=(2,3),offset=(-.1,.2),repeat=(False,True))]
        c=cpu.prepare(mats);g=self.prepare(mats)
        try:
            for samples in (1,2,4,8):
                a=cpu.rasterize(t,u,ids,c,(0,0,0),(4,4,4),1,samples)
                b=gpu.rasterize(t,u,ids,g,(0,0,0),(4,4,4),1,samples)
                again=gpu.rasterize(t,u,ids,g,(0,0,0),(4,4,4),1,samples)
                for k in a:
                    np.testing.assert_allclose(a[k],b[k],atol=2e-7,rtol=0)
                    np.testing.assert_array_equal(b[k],again[k])
        finally:g.close()

    def test_cross_tile_boundary_bytes_and_empty_tile(self):
        t=np.array([[[7,1,.5],[9,1,.5],[9,3,.5]],[[7,1,.5],[9,3,.5],[7,3,.5]]])
        u=np.zeros((2,3,2));ids=np.zeros(2,dtype=int);m=[Surface(np.ones((1,1,4)),[1,0,0])]
        for origin in ((0,0,0),(8,0,0),(16,0,0)):
            a=build_tile(t,u,ids,m,origin,8,8,backend='compiled',allow_empty=True)
            b=build_tile(t,u,ids,m,origin,8,8,backend=self.backend,allow_empty=True)
            self.assertEqual(a[:2],b[:2])

    def test_invalid_material_index_rejected_before_device_access(self):
        g=self.prepare([Surface(np.ones((1,1,4)),[1,1,1])])
        try:
            with self.assertRaisesRegex(ValueError,'material index'):
                gpu.rasterize(np.zeros((1,3,3)),np.zeros((1,3,2)),[1],g,(0,0,0),(1,1,1),1,2)
        finally:g.close()

    backend='cuda'

    def test_reused_scratch_handles_growth_empty_and_small_scenes(self):
        rng=np.random.default_rng(921)
        t=rng.uniform(-1,5,(160,3,3));u=rng.uniform(-1,2,(160,3,2))
        ids=np.zeros(160,dtype=np.int64)
        mats=[Surface(np.ones((1,1,4)),[.4,.6,.8])]
        g=self.prepare(mats);c=cpu.prepare(mats)
        try:
            for n,shape,origin in ((160,(2,2,2),(0,0,0)),(160,(5,4,3),(0,0,0)),(160,(2,2,2),(20,20,20)),(1,(2,2,2),(0,0,0)),(0,(2,2,2),(0,0,0)),(160,(3,3,3),(0,0,0))):
                a=cpu.rasterize(t[:n],u[:n],ids[:n],c,origin,shape,1,2)
                b=gpu.rasterize(t[:n],u[:n],ids[:n],g,origin,shape,1,2)
                for k in a:np.testing.assert_allclose(a[k],b[k],atol=2e-7,rtol=0)
        finally:g.close()

    def test_native_float32_storage_preserves_double_sampling(self):
        rng=np.random.default_rng(81)
        t=rng.uniform(-1,5,(150,3,3));u=rng.uniform(-2,2,(150,3,2));ids=np.zeros(150,dtype=np.int64)
        texture=rng.random((7,8,4)).astype(np.float32)
        native=[Surface(texture,[.8,.7,.6],alpha_test=.3)]
        promoted=[Surface(texture.astype(np.float64),[.8,.7,.6],alpha_test=.3)]
        g=self.prepare(native)
        try:
            from numba.typed import List
            packed=cpu.prepare(promoted)
            old_textures=List()
            for texture in packed[0]:old_textures.append(texture.astype(np.float64))
            a=cpu.rasterize(t,u,ids,(old_textures,*packed[1:]),(0,0,0),(4,4,4),1,4)
            b=gpu.rasterize(t,u,ids,g,(0,0,0),(4,4,4),1,4)
            for k in a:np.testing.assert_array_equal(a[k],b[k])
        finally:g.close()


@unittest.skipUnless((Path(__file__).resolve().parents[1]/'outputs/cuda/voxel_raster_optix.dll').exists(),'optional OptiX DLL not built')
class OptixTests(CudaTests):
    prepare=staticmethod(gpu.prepare_optix)
    backend='optix'

    def test_batched_bricks_match_single_bricks_with_mixed_sizes(self):
        rng=np.random.default_rng(734)
        t=rng.uniform(-1,9,(160,3,3))+[4096,4096,256]
        u=rng.uniform(-1,2,(160,3,2));ids=np.zeros(160,dtype=np.int64)
        mats=[Surface(rng.random((3,4,4)).astype(np.float32),[.6,.8,.9],alpha_test=.4)]
        g=self.prepare(mats)
        bricks=np.array([[4096,4096,256,.5],[4100,4096,256,1],[4200,4200,256,2]])
        try:
            g.set_scene(t,u,ids)
            for samples in (1,2,4):
                output=g.raster_batch(bricks,samples)
                for n,b in enumerate(bricks):
                    reference=g.raster_scene(b[:3],(16,16,16),b[3],samples)
                    for key,start in [('opacity',0),('albedo',3),('normals',6)]:
                        np.testing.assert_array_equal(output[n,...,start:start+3],reference[key])
        finally:g.close()

    def test_batched_tile_pipeline_preserves_files(self):
        from unittest.mock import patch
        rng=np.random.default_rng(18)
        t=rng.uniform(0,15,(140,3,3));u=np.zeros((140,3,2));ids=np.zeros(140,dtype=int)
        mats=[Surface(np.ones((1,1,4)),[.5,.8,.3])]
        with patch.dict('os.environ',{'GLUEMAPPER_GPU_BATCH':'1'}):
            expected=build_tile(t,u,ids,mats,(0,0,0),16,8,backend='optix')[:2]
        for pipeline in ('0','1'):
            with patch.dict('os.environ',{'GLUEMAPPER_GPU_BATCH':'4','GLUEMAPPER_GPU_PIPELINE':pipeline}):
                actual=build_tile(t,u,ids,mats,(0,0,0),16,8,backend='optix')[:2]
                self.assertEqual(actual,expected)

    def test_async_and_graph_batches_preserve_output_across_updates(self):
        from unittest.mock import patch
        rng=np.random.default_rng(829)
        t=rng.uniform(-1,9,(140,3,3));u=rng.uniform(-1,2,(140,3,2));ids=np.zeros(140,dtype=int)
        mats=[Surface(np.ones((1,1,4)),[.3,.6,.8])]
        bricks=np.array([[0,0,0,.5],[0,0,0,1],[100,100,0,2]])
        for mode in ('GLUEMAPPER_GPU_ASYNC','GLUEMAPPER_GPU_GRAPHS'):
            with patch.dict('os.environ',{mode:'1'}):
                g=self.prepare(mats)
                try:
                    g.set_scene(t,u,ids)
                    for n,samples in ((1,1),(3,2),(2,4),(1,8)):
                        output=g.raster_batch(bricks[:n],samples)
                        for k,b in enumerate(bricks[:n]):
                            ref=g.raster_scene(b[:3],(16,16,16),b[3],samples)
                            for key,start in [('opacity',0),('albedo',3),('normals',6)]:np.testing.assert_array_equal(output[k,...,start:start+3],ref[key])
                finally:g.close()

    def test_experimental_hardware_triangles_opaque_interior(self):
        from unittest.mock import patch
        t=np.repeat(np.array([[[0,0,.5],[8,0,.5],[0,8,.5]]]),140,axis=0)
        mats=[Surface(np.ones((1,1,4)),[.2,.5,.8])]
        results=[]
        for mode in ('0','1'):
            with patch.dict('os.environ',{'GLUEMAPPER_OPTIX_TRIANGLES':mode}):
                g=self.prepare(mats)
                try:
                    g.set_scene(t,np.zeros((140,3,2)),np.zeros(140,dtype=int))
                    results.append(g.raster_batch([[0,0,0,1]],2))
                finally:g.close()
        np.testing.assert_array_equal(*results)

    def test_persistent_scene_reuses_geometry_across_bricks_at_large_coordinates(self):
        rng=np.random.default_rng(437)
        t=rng.uniform(-1,9,(160,3,3))+[4096,4096,256]
        u=rng.uniform(-1,2,(160,3,2));ids=np.zeros(160,dtype=np.int64)
        mats=[Surface(rng.random((3,4,4)).astype(np.float32),[.6,.8,.9],alpha_test=.4)]
        g=self.prepare(mats);c=cpu.prepare(mats)
        try:
            g.set_scene(t,u,ids)
            for origin in ((4096,4096,256),(4100,4096,256)):
                a=cpu.rasterize(t,u,ids,c,origin,(4,4,4),1,2)
                b=g.raster_scene(origin,(4,4,4),1,2)
                for k in a:np.testing.assert_allclose(a[k],b[k],atol=2e-7,rtol=0)
        finally:g.close()


if __name__=='__main__':unittest.main()
