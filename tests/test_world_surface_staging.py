import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from voxel_surfaces import build_tile
from stage_world_surfaces import stage
from validate_world_surfaces import validate,reuse_base

class StagingTests(unittest.TestCase):
    def fixture(self,root):
        scene=root/'scene';scene.mkdir();(scene/'tiles').mkdir();level=root/'level';level.mkdir()
        with zipfile.ZipFile(level/'level.pak','w') as z:z.writestr('mission_mission0.xml','<Mission><Environment><Total_Illumination_v2/></Environment></Mission>')
        source=str(level/'level.pak');sha=hashlib.sha256(Path(source).read_bytes()).hexdigest()
        plan={'errors':{},'pending_categories':{},'source_packages':{source:sha},'level':str(level),'tiles':[{'origin':[0,0,0],'placements':[]}]}
        (scene/'plan.json').write_text(json.dumps(plan))
        idx,vox,check=build_tile(np.empty((0,3,3)),np.empty((0,3,2)),np.empty(0,np.int32),[],(0,0,0),allow_empty=True)
        name='0128_0128_0128_0256'
        (scene/'tiles'/(name+'.idx')).write_bytes(idx);(scene/'tiles'/(name+'.vox')).write_bytes(vox)
        (scene/'tiles'/(name+'.json')).write_text(json.dumps({'status':'built','origin':[0,0,0],'sha256':hashlib.sha256(idx+vox).hexdigest()}))
        return scene,plan,name

    def test_stage_validates_and_sets_mode_without_installing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);scene,plan,name=self.fixture(root)
            baseline=(Path(plan['level'])/'level.pak').read_bytes();r=stage(scene,root/'staged')
            self.assertFalse(r['installed']);self.assertEqual(r['tiles'],1)
            self.assertEqual((Path(plan['level'])/'level.pak').read_bytes(),baseline)
            with zipfile.ZipFile(root/'staged/packages/svo-part0.pak') as z:self.assertEqual(set(z.namelist()),{'terrain/svo/'+name+'.idx','terrain/svo/'+name+'.vox'})
            with zipfile.ZipFile(root/'staged/packages/level.pak') as z:self.assertIn(b'IntegrationMode="1"',z.read('mission_mission0.xml'))

    def test_incomplete_coverage_and_corrupt_tile_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);scene,plan,name=self.fixture(root)
            plan['pending_categories']={'unknown':1};(scene/'plan.json').write_text(json.dumps(plan))
            with self.assertRaises(ValueError):stage(scene,root/'bad')
            self.assertFalse((root/'bad').exists())
            (scene/'tiles'/(name+'.vox')).write_bytes(b'bad')
            self.assertEqual(len(validate(scene)['failed']),1)

    def test_missing_vegetation_cannot_pass_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);scene,plan,name=self.fixture(root)
            plan['tiles'][0]['vegetation']=[0];(scene/'plan.json').write_text(json.dumps(plan))
            self.assertIn('Vegetation coverage mismatch',validate(scene)['failed'][0]['error'])

if __name__=='__main__':unittest.main()
