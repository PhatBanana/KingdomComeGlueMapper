"""Characters convert in worker processes but are registered in request order."""
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from build_quest_people_test import convert_characters


def fake_convert(index, delay, notify=None):
    time.sleep(delay)
    return dict(person=dict(name=str(index)), pid=os.getpid(), bakes=os.environ.get('GLUEMAPPER_BAKE_WORKERS'))


class ParallelCharacterTests(unittest.TestCase):
    def test_worker_results_keep_job_order_and_share_bake_budget(self):
        jobs = [(index, 0.3 if index == 0 else 0.0) for index in range(4)]
        with patch.dict(os.environ, {'GLUEMAPPER_CHARACTER_WORKERS': '2', 'GLUEMAPPER_BAKE_WORKERS': '6'}):
            results = list(convert_characters(jobs, lambda message: None, lambda: False, convert=fake_convert))
        self.assertEqual([r['person']['name'] for r in results], ['0', '1', '2', '3'])
        self.assertEqual({r['bakes'] for r in results}, {'3'})
        self.assertNotIn(os.getpid(), {r['pid'] for r in results})

    def test_one_worker_converts_in_this_process_with_progress(self):
        messages = []
        with patch.dict(os.environ, {'GLUEMAPPER_CHARACTER_WORKERS': '1'}):
            results = list(convert_characters([(0, 0), (1, 0)], messages.append, lambda: False, convert=fake_convert))
        self.assertEqual({r['pid'] for r in results}, {os.getpid()})

    def test_one_process_converts_the_next_person_while_textures_compress(self):
        from concurrent.futures import Future
        import build_quest_people_test as people
        tickets, events = [Future(), Future()], []

        def convert(index, notify=None, encodes=None):
            self.assertIsNotNone(encodes)
            events.append(('convert', index))
            if index == 1:
                tickets[0].set_result(None)  # the GPU finishes person 0 during person 1
                tickets[1].set_result(None)
            return dict(person=dict(name=str(index)),
                        _finish=(None, None, Path('out'), f'ns{index}', Path('data'), 0.0, tickets[index]))

        def pack(folder, data_dir, namespace):
            events.append(('pack', namespace))
            return [], {'Libs/' + namespace: b''}

        with patch.dict(os.environ, {'GLUEMAPPER_CHARACTER_WORKERS': '1'}), \
                patch.object(people, 'convert_character', convert), patch.object(people, 'write_actor_paks', pack):
            results = list(convert_characters([(0,), (1,)], lambda message: None, lambda: False))
        self.assertEqual(events, [('convert', 0), ('convert', 1), ('pack', 'ns0'), ('pack', 'ns1')])
        self.assertEqual([r['person']['name'] for r in results], ['0', '1'])
        self.assertEqual([r['libs'] for r in results], [{'Libs/ns0': b''}, {'Libs/ns1': b''}])
        self.assertTrue(all('_finish' not in r and 'paks' not in r for r in results))

    def test_cancel_stops_before_the_next_character(self):
        with patch.dict(os.environ, {'GLUEMAPPER_CHARACTER_WORKERS': '2'}):
            results = convert_characters([(0, 0), (1, 0), (2, 0)], lambda message: None, lambda: True, convert=fake_convert)
            with self.assertRaises(InterruptedError):
                next(results)

    def test_low_memory_falls_back_to_one_process(self):
        with patch('bounded_pool.available_memory', return_value=2 * 1024**3), patch.dict(os.environ, {}, clear=False):
            os.environ.pop('GLUEMAPPER_CHARACTER_WORKERS', None)
            results = list(convert_characters([(0, 0), (1, 0)], lambda message: None, lambda: False, convert=fake_convert))
        self.assertEqual({r['pid'] for r in results}, {os.getpid()})


if __name__ == '__main__':
    unittest.main()
