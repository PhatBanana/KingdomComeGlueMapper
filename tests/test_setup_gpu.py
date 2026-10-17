"""Frozen GPU discovery, payload integrity and developer-policy isolation."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_gpu import gpu_directory, hybrid_environment, validate_bundle, probe


class SetupGpuTests(unittest.TestCase):
    def test_frozen_paths_and_policy_restored_even_after_failure(self):
        with patch.object(sys,'frozen',True,create=True), patch.object(sys,'_MEIPASS','C:/bundle',create=True), patch.dict(os.environ,{'GLUEMAPPER_GPU_BATCH':'3','GLUEMAPPER_OPTIX_TRIANGLES':'1'}):
            self.assertEqual(gpu_directory(),Path('C:/bundle/bake-gpu'))
            with self.assertRaises(ValueError):
                with hybrid_environment():
                    self.assertEqual(os.environ['GLUEMAPPER_GPU_BATCH'],'64')
                    self.assertEqual(os.environ['GLUEMAPPER_OPTIX_TRIANGLES'],'0')
                    self.assertEqual(Path(os.environ['GLUEMAPPER_OPTIX_DLL']),Path('C:/bundle/bake-gpu/voxel_raster_optix.dll'))
                    raise ValueError('cancelled')
            self.assertEqual(os.environ['GLUEMAPPER_GPU_BATCH'],'3')
            self.assertEqual(os.environ['GLUEMAPPER_OPTIX_TRIANGLES'],'1')

    def test_payload_and_sources_are_verified(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            names=('voxel_raster_optix.dll','voxel_optix.ptx','voxel_raster_cuda.cu','voxel_optix_shared.h','voxel_optix_device.cu','voxel_optix_host.h')
            for name in names:(root/name).write_bytes(name.encode())
            digests={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}
            meta=dict(dll_sha256=digests[names[0]],ptx_sha256=digests[names[1]],source_sha256=digests[names[2]],extra_sources={name:digests[name] for name in names[3:]})
            (root/'voxel_raster_optix.build.json').write_text(json.dumps(meta))
            validate_bundle(root,root)
            for name in names:
                (root/name).write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'Stale or modified'):validate_bundle(root,root)
                (root/name).write_bytes(name.encode())
            (root/names[0]).unlink()
            with self.assertRaisesRegex(RuntimeError,'Missing hybrid'):validate_bundle(root,root)

    def test_unavailable_gpu_is_reported_as_cpu_not_success(self):
        with patch('setup_gpu.validate_bundle',side_effect=RuntimeError('GPU payload unavailable')):
            result=probe()
        self.assertFalse(result['available'])
        self.assertEqual(result['backend'],'compiled')
        self.assertIn('unavailable',result['reason'])

if __name__=='__main__':unittest.main()
