"""Caching must retain asset precedence, bytes, and bounded working sets."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from geometry_opacity import Assets
from world_surface_tiles import MeshCache,TextureCache


class CacheTests(unittest.TestCase):
    def test_archive_reuse_eviction_and_close(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(10):
                with zipfile.ZipFile(Path(folder)/f'{i:02}.pak','w') as z:z.writestr(f'{i}.bin',bytes([i]))
            assets=Assets(folder)
            with patch('geometry_opacity.zipfile.ZipFile',wraps=zipfile.ZipFile) as opens:
                for _ in range(3):self.assertEqual(assets.get('0.bin'),b'\0')
                self.assertEqual(opens.call_count,1)
                for i in range(1,10):self.assertEqual(assets.get(f'{i}.bin'),bytes([i]))
                self.assertLessEqual(len(assets._archives),8)
                self.assertEqual(assets.get('0.bin'),b'\0')
            handles=list(assets._archives.values());assets.close()
            self.assertTrue(all(z.fp is None for z in handles))

    def test_mesh_cache_keeps_recent_entries_and_accounts_replacements(self):
        cache=MeshCache(24)
        def value(n):return ({},np.full(1,n,dtype=np.int64),np.zeros(0),np.zeros(0))
        for i in range(3):cache[i]=value(i)
        self.assertEqual(cache[0][1][0],0)
        cache[3]=value(3)
        self.assertNotIn(1,cache);self.assertEqual(cache.bytes,24)
        cache[0]=value(8);self.assertEqual(cache.bytes,24)
        self.assertEqual(cache[0][1][0],8)

    def test_texture_cache_recency(self):
        cache=TextureCache(16)
        cache['a']=np.zeros(1);cache['b']=np.zeros(1)
        _=cache['a'];cache['c']=np.zeros(1)
        self.assertEqual(list(cache),['a','c'])


if __name__=='__main__':unittest.main()
