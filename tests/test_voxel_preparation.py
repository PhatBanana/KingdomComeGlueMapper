"""Acceleration preserves byte colours and conservative octree boundaries."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from voxel_surfaces import decode_rgba_bytes,srgb_to_linear
from voxel_raster_fast import filter_bounds


class PreparationTests(unittest.TestCase):
    def test_batch_memory_retry_preserves_order_and_propagates_other_errors(self):
        import ctypes as ct
        from voxel_raster_cuda import Prepared
        class FakeGpu:
            message=b'CUDA out of memory'
            calls=[]
            def vr_batch(self,handle,source,count,samples,dest):
                self.calls.append(count)
                if count>2:return 1
                b=np.ctypeslib.as_array(ct.cast(source,ct.POINTER(ct.c_double)),shape=(count*4,)).reshape(count,4)
                output=np.ctypeslib.as_array(ct.cast(dest,ct.POINTER(ct.c_double)),shape=(count*4096*9,)).reshape(count,16,16,16,9)
                for n in range(count):output[n]=b[n,0]
                return 0
            def vr_error(self):return self.message
            def vr_destroy(self,handle):pass
        g=Prepared.__new__(Prepared);g.handle=1;g.dll=FakeGpu()
        try:
            b=np.array([[n,0,0,1] for n in range(7)],float)
            actual=g.raster_batch(b)
            np.testing.assert_array_equal(actual[:,0,0,0,0],np.arange(7))
            self.assertIn(7,g.dll.calls);self.assertIn(2,g.dll.calls)
            g.dll.message=b'illegal memory access'
            with self.assertRaisesRegex(RuntimeError,'illegal memory access'):g.raster_batch(b)
        finally:g.close()

    def test_all_decoded_byte_values_match_original_arithmetic(self):
        raw=np.arange(256,dtype=np.uint8).reshape(16,16,1).repeat(4,axis=2)
        expected=raw.astype(np.float32)/255
        expected[...,:3]=srgb_to_linear(expected[...,:3])
        np.testing.assert_array_equal(decode_rgba_bytes(raw),expected)

    def test_bounds_match_reference_including_touching_and_reordered_candidates(self):
        rng=np.random.default_rng(913)
        lo=rng.integers(-16,32,size=(1000,3)).astype(float)
        hi=lo+rng.integers(0,20,size=lo.shape)
        candidates=rng.permutation(len(lo))
        for pos in (np.array([0,0,0]),np.array([8,16,24])):
            expected=candidates[np.all(hi[candidates]>=pos,axis=1)&np.all(lo[candidates]<pos+16,axis=1)]
            np.testing.assert_array_equal(filter_bounds(lo,hi,candidates,pos,16),expected)


if __name__=='__main__':unittest.main()
