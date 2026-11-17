import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import character_work_adapters as registry


def entry(tree_name, **extra):
    return dict(behavior=dict(tree_file='final/sa_test.xml', tree_name=tree_name),
                arrival=dict(EntityGuid='{G}', EntityId='7'), start_minute=480, end_minute=720, **extra)


def fake(name, trees, activity=''):
    module = types.ModuleType(name)
    module.supports = lambda e: e['behavior']['tree_name'] in trees
    module.resolve = lambda e, archive, source, reader: dict(e, test_work=dict(tree=e['behavior']['tree_name']))
    module.calls = []

    def bind(mission, scheduler, person, e, target):
        module.calls.append(person)
        return types.SimpleNamespace(get=lambda k: 'JOB'), [('JOB', 'SEAT', '_,use')], dict(person=person, interval=[e['start_minute'], e['end_minute']])
    module.bind = bind
    if activity:
        module.ACTIVITY = activity
    return module


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.module = fake('fake_work', {'tanner'}, 'craft')
        patches = [mock.patch.dict(sys.modules, {'fake_work': self.module}),
                   mock.patch.object(registry, 'ADAPTERS', (registry.Adapter('fake_work', 'test_work'),
                                                            registry.Adapter('missing_adapter_module', 'x')))]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def test_supports_by_tree_and_skips_absent_modules(self):
        self.assertTrue(registry.supports(entry('tanner')))
        self.assertFalse(registry.supports(entry('baker')))

    def test_resolve_requires_source_and_marks_entry(self):
        self.assertIsNone(registry.resolve(entry('baker'), None, None, None))
        with self.assertRaises(ValueError):
            registry.resolve(entry('tanner'), None, None, None)
        self.assertEqual(registry.resolve(entry('tanner'), None, 'src', 'reader')['test_work'], dict(tree='tanner'))

    def test_overlapping_adapters_fail_loudly(self):
        other = fake('other_work', {'tanner'})
        with mock.patch.dict(sys.modules, {'other_work': other}), mock.patch.object(
                registry, 'ADAPTERS', (registry.Adapter('fake_work', 'a'), registry.Adapter('other_work', 'b'))):
            with self.assertRaises(ValueError):
                registry.supports(entry('tanner'))

    def test_bind_pools_repeated_intervals_on_one_anchor(self):
        pools = {}
        first = entry('tanner', test_work=dict(tree='tanner'))
        job, links, report, activity = registry.bind(None, None, 'p', first, None, pools)
        self.assertEqual((activity, links), ('craft', [('JOB', 'SEAT', '_,use')]))
        second = dict(first, start_minute=780, end_minute=1020)
        self.assertEqual(registry.bind(None, None, 'p', second, None, pools), (None, [], None, None))
        self.assertEqual(report['intervals'], [[480, 720], [780, 1020]])
        self.assertEqual(self.module.calls, ['p'])
        self.assertIsNone(registry.bind(None, None, 'p', entry('baker'), None, pools))

    def test_bound_programs_publish_without_schedules(self):
        # The population stage calls job_resources(..., {}) after binding.
        self.module.entry_resources = lambda e: ('TPL', {'AI/gluemapper/x.xml': b'<x/>'})
        with mock.patch.dict(registry._BOUND, clear=True):
            registry.bind(None, None, 'p', entry('tanner', test_work=dict(tree='tanner')), None, {})
            self.assertEqual(registry.resources({}, {'TPL'}), {'AI/gluemapper/x.xml': b'<x/>'})
            self.assertEqual(registry.resources({}, {'OTHER'}), {})

    def test_conflicting_pool_contract_fails(self):
        pools = {}
        registry.bind(None, None, 'p', entry('tanner', test_work=dict(tree='a')), None, pools)
        with self.assertRaises(ValueError):
            registry.bind(None, None, 'p', entry('tanner', test_work=dict(tree='b')), None, pools)


if __name__ == '__main__':
    unittest.main()
