import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_build_cache import environment, file_hash
from setup_cache_import import import_build, candidates, approved
from setup_campaign import RECEIPT
from test_setup_build_cache import pak


class CacheImportTests(unittest.TestCase):
    def old_build(self, root):
        build=root/'old';package=build/'package/map';level=package/'Data/Levels/map'
        pak(level/'svo-part0.pak',{'terrain/svo/test':b'completed lighting'})
        pak(level/'level.pak',{'objects_mission0.xml':b'old quests must never be imported'})
        shard=level/'svo-part0.pak'
        (build/'job.json').write_text('{}')
        receipt=dict(files={'Data/Levels/map/svo-part0.pak':file_hash(shard)},
                     baking=dict(preset='all',levels=[dict(level='map',tiles=1)]))
        (package/RECEIPT).write_text(json.dumps(receipt))
        staging=build/'baking/hash/map/plan-test/staged-test/staging.json'
        staging.parent.mkdir(parents=True)
        staging.write_text(json.dumps(dict(level_dir=str(level),tiles=1,limitations=[],
            vegetation_gi_upgrade=None,packages={'svo-part0.pak':file_hash(shard)})))
        return build,shard

    def test_import_is_independent_and_requires_explicit_selection(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);build,shard=self.old_build(root)
            result=import_build(build,root/'workspace')
            self.assertEqual(len(candidates(root/'workspace','all')),1)
            self.assertEqual(candidates(root/'workspace','buildings'),[])
            with environment({'workspace':str(root/'workspace')}):
                self.assertIsNone(approved('lighting',level='map',preset='all'))
            shard.write_bytes(b'old job later changed')
            with environment({'workspace':str(root/'workspace'),'imported_cache':result['id']}):
                hit=approved('lighting',level='map',preset='all')
                self.assertEqual([p.name for p in hit[0].iterdir()],['svo-part0.pak'])
                self.assertIsNone(approved('lighting',level='map',preset='buildings'))
                (hit[0]/'svo-part0.pak').write_bytes(b'damaged cache')
                with self.assertRaisesRegex(ValueError,'damaged'):approved('lighting',level='map',preset='all')

    def test_modified_incomplete_or_cancelled_build_never_published(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);build,shard=self.old_build(root)
            with self.assertRaises(InterruptedError):import_build(build,root/'workspace',lambda:True)
            self.assertEqual(candidates(root/'workspace','all'),[])
            shard.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):import_build(build,root/'workspace')
            self.assertEqual(candidates(root/'workspace','all'),[])

    def test_missing_staging_report_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);build,_=self.old_build(root)
            next((build/'baking').rglob('staging.json')).unlink()
            with self.assertRaisesRegex(ValueError,'staging report'):import_build(build,root/'workspace')


if __name__=='__main__':unittest.main()
