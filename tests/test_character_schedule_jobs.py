import tempfile
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_schedule_jobs import bind_jobs


class JobDependencyTests(unittest.TestCase):
    def test_unconverted_work_is_reported_with_its_dependencies(self):
        entry = dict(behavior=dict(tree_file='final/sa_farm.xml', tree_name='Farmer'),
                     area=dict(EntityGuid='10'), target_links=[dict(Name='tool', TargetId='4')])
        files = {'objects_mission0.xml': b'<Objects/>',
                 'tables/ai/scheduler.xml': b'<Root><Schedulers/></Root>',
                 'waitinglinks.xml': b'<StaticLinksInfo version="1"/>'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.pak'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('objects_mission0.xml', '<Objects/>')
            with zipfile.ZipFile(path) as archive:
                _, report = bind_jobs(files, {'source_actor': [entry]}, archive, Path('.'), {})
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]['source_behavior'], entry['behavior'])
        self.assertEqual(report[0]['source_links'], entry['target_links'])
        self.assertTrue(report[0]['pending'])
        self.assertFalse(report[0]['runtime_verified'])


if __name__ == '__main__': unittest.main()
