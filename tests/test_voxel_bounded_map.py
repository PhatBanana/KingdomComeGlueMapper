"""Ordered, bounded CPU scheduling on both sides of Python 3.14."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from voxel_surfaces import _bounded_map


class BoundedMapTests(unittest.TestCase):
    def test_pre314_bounds_generator_lookahead_and_preserves_order(self):
        consumed=[]
        def jobs():
            for value in range(11):
                consumed.append(value)
                yield value
        with patch('voxel_surfaces.sys.version_info', (3,13)), ThreadPoolExecutor(max_workers=3) as pool:
            values=_bounded_map(pool,lambda x:x*x,jobs(),3)
            self.assertEqual(next(values),0)
            self.assertEqual(consumed,[0,1,2])
            self.assertEqual([0]+list(values),[x*x for x in range(11)])

    def test_pre314_empty_and_worker_exception(self):
        def fail(value):raise ValueError('worker failed')
        with patch('voxel_surfaces.sys.version_info',(3,13)), ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(_bounded_map(pool,abs,[],2)),[])
            with self.assertRaisesRegex(ValueError,'worker failed'):
                list(_bounded_map(pool,fail,[1],2))

    def test_314_keeps_native_streaming_buffer(self):
        pool=Mock();pool.map.return_value=iter([1,2]);jobs=iter([-1,-2])
        with patch('voxel_surfaces.sys.version_info',(3,14)):
            self.assertEqual(list(_bounded_map(pool,abs,jobs,2)),[1,2])
        pool.map.assert_called_once_with(abs,jobs,buffersize=2)
