"""Deferred character texture bakes complete before their outputs are read."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bake_pool


class BakePoolTests(unittest.TestCase):
    def test_bakes_run_in_the_pool_and_wait_surfaces_failures(self):
        with tempfile.TemporaryDirectory() as t, ThreadPoolExecutor(2) as executor, \
             patch.object(bake_pool, 'pool', return_value=executor):
            bakes = bake_pool.Bakes()
            image = Image.new('RGBA', (4, 4), (255, 128, 0, 255))
            for i in range(5):  # more than twice the workers, so the queue bound is exercised
                bakes(Path(t) / f'bake{i}.dds', image, ET.Element('Material', Diffuse='1,1,1'))
            image.putpixel((0, 0), (0, 0, 0, 255))  # the caller may reuse its image afterwards
            bakes.wait()
            payloads = {(Path(t) / f'bake{i}.dds').read_bytes() for i in range(5)}
            self.assertEqual(len(payloads), 1)  # every bake saw the original pixels
            self.assertEqual(next(iter(payloads))[:4], b'DDS ')
            bakes(Path(t) / 'missing/dir/bake.dds', image, ET.Element('Material'))
            with self.assertRaisesRegex(RuntimeError, 'Character texture bake'):
                bakes.wait()
            self.assertEqual(bakes.pending, [])

    def test_release_closes_the_shared_pool(self):
        with patch.object(bake_pool, 'ProcessPoolExecutor', ThreadPoolExecutor):
            first = bake_pool.pool()
            self.assertIs(bake_pool.pool(), first)
            bake_pool.release()
            self.assertIsNone(bake_pool._POOL)
            with self.assertRaises(RuntimeError): first.submit(print)  # shut down

    def fake_bakes(self, written, release, started):
        """bake_float_dds stand-in: 'fail' raises once 'held' has started; 'held' blocks until
        release and then writes its output; anything else records that it ran."""
        def bake(path, image, material, specular=None):
            if path.name.startswith('held'):
                started.set(); release.wait(5); written.append(path.name)
            elif path.name == 'fail':
                started.wait(5); raise ValueError('bad pixels')
            elif path.name == 'boom':
                raise ValueError('bad pixels')
            else:
                written.append(path.name)
        return patch.object(bake_pool, 'bake_float_dds', bake)

    def test_a_failed_bake_cancels_queued_bakes_and_joins_running_ones_before_raising(self):
        import threading
        written, release, started = [], threading.Event(), threading.Event()
        image = Image.new('RGBA', (1, 1))
        with ThreadPoolExecutor(2) as executor, patch.object(bake_pool, 'pool', return_value=executor), \
             self.fake_bakes(written, release, started):
            bakes = bake_pool.Bakes()
            # Two workers: 'fail' and 'held' start; when 'fail' raises its worker takes
            # 'held2', so 'queued' is still waiting when the failure is handled.
            for name in ('fail', 'held', 'held2', 'queued'):
                bakes(Path(name), image, ET.Element('Material'))
            threading.Timer(0.3, release.set).start()  # both held bakes are running when 'fail' raises
            with self.assertRaisesRegex(RuntimeError, 'Character texture bake fail: bad pixels'):
                bakes.wait()
            after = list(written)
            self.assertEqual(sorted(after), ['held', 'held2'])  # joined before wait() raised
            self.assertEqual(bakes.pending, [])
            executor.shutdown(wait=True)
            self.assertEqual(written, after)  # 'queued' was cancelled; nothing ran after the failure

    def test_a_conversion_error_after_submission_joins_its_bakes_and_keeps_the_error(self):
        import threading
        written, release, started = [], threading.Event(), threading.Event()
        image = Image.new('RGBA', (1, 1))
        with ThreadPoolExecutor(1) as executor, patch.object(bake_pool, 'pool', return_value=executor), \
             self.fake_bakes(written, release, started):
            with self.assertRaisesRegex(KeyError, 'missing slot'):
                with bake_pool.Bakes() as bakes:
                    bakes(Path('held'), image, ET.Element('Material'))
                    bakes(Path('queued'), image, ET.Element('Material'))
                    started.wait(5); threading.Timer(0.3, release.set).start()
                    raise KeyError('missing slot')
            self.assertEqual(written, ['held'])

    def test_a_failure_found_at_the_queue_bound_also_drains_the_batch(self):
        import threading
        written, release, started = [], threading.Event(), threading.Event()
        release.set(); image = Image.new('RGBA', (1, 1))
        with ThreadPoolExecutor(1) as executor, patch.object(bake_pool, 'pool', return_value=executor), \
             self.fake_bakes(written, release, started):
            bakes = bake_pool.Bakes()  # one worker: the third submission first finishes the oldest bake
            bakes(Path('boom'), image, ET.Element('Material')); bakes(Path('held'), image, ET.Element('Material'))
            with self.assertRaisesRegex(RuntimeError, 'Character texture bake boom'):
                bakes(Path('third'), image, ET.Element('Material'))
            self.assertEqual(bakes.pending, [])
            after = list(written); executor.shutdown(wait=True)
            self.assertEqual(written, after)  # every bake of the batch had finished or was cancelled
            self.assertNotIn('third', written)

    def test_leaving_the_block_normally_waits_for_every_bake(self):
        written, image = [], Image.new('RGBA', (1, 1))
        with ThreadPoolExecutor(2) as executor, patch.object(bake_pool, 'pool', return_value=executor), \
             patch.object(bake_pool, 'bake_float_dds', lambda path, *a: written.append(path.name)):
            with bake_pool.Bakes() as bakes:
                for i in range(5):
                    bakes(Path(str(i)), image, ET.Element('Material'))
            self.assertEqual(sorted(written), ['0', '1', '2', '3', '4'])
