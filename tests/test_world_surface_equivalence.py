import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from reuse_equivalent_world_tiles import reuse
from voxel_surfaces import build_tile
from world_surface_tiles import tile_signature,gpu_configuration


class EquivalenceTests(unittest.TestCase):
    def fixture(self,root,extra=False):
        old=root/'old';new=root/'new'
        for path in (old,new):
            (path/'meshes').mkdir(parents=True)
            (path/'placements.json').write_text('[]')
        (old/'tiles').mkdir()
        package=root/'source';package.write_bytes(b'current')
        plan={'source_packages':{str(package):hashlib.sha256(b'current').hexdigest()},
              'asset_catalog_digest':'catalog','pak_root':'assets','overrides':[],
              'landscape_limitations':[],'tiles':[{'origin':[0,0,0],'placements':[]}]}
        before=json.loads(json.dumps(plan));before['source_packages'][str(package)]='prior-mission-only-package'
        (old/'plan.json').write_text(json.dumps(before))
        idx,vox,_=build_tile(np.empty((0,3,3)),np.empty((0,3,2)),np.empty(0,np.int32),[],(0,0,0),allow_empty=True)
        name='0128_0128_0128_0256'
        for ext,data in [('.idx',idx),('.vox',vox)]:(old/'tiles'/(name+ext)).write_bytes(data)
        report={'status':'built','sha256':hashlib.sha256(idx+vox).hexdigest(),
                'signature':tile_signature('reference',before['asset_catalog_digest'],before,before['tiles'][0],2,True,'auto',gpu_configuration())}
        (old/'tiles'/(name+'.json')).write_text(json.dumps(report))
        if extra:
            np.savez(new/'vegetation.npz',transforms=np.eye(4)[None,:3,:],groups=np.array([0],np.uint16))
            plan['vegetation']={'groups':{'0':{'cache_key':'new-tree'}},'sha256':hashlib.sha256((new/'vegetation.npz').read_bytes()).hexdigest()}
            plan['tiles'][0]['vegetation']=[0]
        (new/'plan.json').write_text(json.dumps(plan))
        return new,old

    def test_unchanged_decoded_inputs_reuse_despite_mission_package_change(self):
        with tempfile.TemporaryDirectory() as d:
            new,old=self.fixture(Path(d));self.assertEqual(reuse(new,old,'reference')['reused'],1)

    def test_added_tree_forces_rebuild(self):
        with tempfile.TemporaryDirectory() as d:
            new,old=self.fixture(Path(d),True);self.assertEqual(reuse(new,old,'reference')['rebuild'],1)

    def test_unverified_builder_refused(self):
        with tempfile.TemporaryDirectory() as d:
            new,old=self.fixture(Path(d))
            with self.assertRaisesRegex(ValueError,'builder'):reuse(new,old,'wrong-code')


if __name__=='__main__':unittest.main()
