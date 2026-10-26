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
        def bake(path, image, material, specular=None, staging=None):
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
             patch.object(bake_pool, 'bake_float_dds', lambda path, *a, **k: written.append(path.name)):
            with bake_pool.Bakes() as bakes:
                for i in range(5):
                    bakes(Path(str(i)), image, ET.Element('Material'))
            self.assertEqual(sorted(written), ['0', '1', '2', '3', '4'])


class BatchedEncodeTests(unittest.TestCase):
    def test_staged_bakes_and_masks_are_written_by_the_batches_when_the_block_ends(self):
        import os
        import texture_encode
        from character_native_materials import bake_float_dds
        calls = []
        def encode(jobs, executable, write=True):
            calls.append(sorted(Path(j.target).name for j in jobs))
            for job in jobs: Path(job.target).write_bytes(b'encoded ' + str(job[2]).encode())
        image = Image.new('RGBA', (64, 64), (200, 100, 50, 255))
        with tempfile.TemporaryDirectory() as t, ThreadPoolExecutor(2) as executor, \
                patch.object(bake_pool, 'pool', return_value=executor), \
                patch.object(texture_encode, 'encode_staged', encode), \
                patch.object(texture_encode, 'texconv_executable', return_value=Path('texconv.exe')), patch.object(texture_encode, '_tool_identity', return_value='fake'), \
                patch.dict(os.environ, {texture_encode.SETTING: '', texture_encode.ENCODER_SETTING: ''}):
            with bake_pool.Bakes() as bakes:
                bakes(Path(t) / 'a_diff.dds', image, ET.Element('Material', Diffuse='1,1,1'))
                bakes.mask(Path(t) / 'a_bgs.dds', image)
                bakes(Path(t) / 'tiny_diff.dds', Image.new('RGBA', (4, 4)), ET.Element('Material'))
                staging = bakes.batches.directory
            self.assertEqual(calls, [['a_bgs.dds', 'a_diff.dds']])
            self.assertEqual((Path(t) / 'a_diff.dds').read_bytes(), b'encoded True')
            self.assertEqual((Path(t) / 'a_bgs.dds').read_bytes(), b'encoded False')
            self.assertEqual((Path(t) / 'tiny_diff.dds').read_bytes()[84:88], b'DX10')   # written directly
            self.assertFalse(Path(staging).exists())

    def test_an_encode_failure_is_reported_after_the_bakes(self):
        import os
        import texture_encode
        def encode(jobs, executable, write=True): raise ValueError('texconv could not encode x_diff.dds')
        with tempfile.TemporaryDirectory() as t, ThreadPoolExecutor(1) as executor, \
                patch.object(bake_pool, 'pool', return_value=executor), \
                patch.object(texture_encode, 'encode_staged', encode), \
                patch.object(texture_encode, 'texconv_executable', return_value=Path('texconv.exe')), patch.object(texture_encode, '_tool_identity', return_value='fake'), \
                patch.dict(os.environ, {texture_encode.SETTING: '', texture_encode.ENCODER_SETTING: ''}):
            with self.assertRaisesRegex(RuntimeError, 'Character texture encode: .*x_diff.dds'):
                with bake_pool.Bakes() as bakes:
                    bakes(Path(t) / 'x_diff.dds', Image.new('RGBA', (64, 64)), ET.Element('Material'))


class DeferredEncodeTests(unittest.TestCase):
    def setUp(self):
        import os
        import threading
        import texture_encode
        self.release, self.calls = threading.Event(), []
        def encode(jobs, executable, write=True):
            self.release.wait(5)
            self.calls.append(len(jobs))
            for job in jobs:
                if 'bad' in job.target: raise ValueError('texconv could not encode ' + job.target)
                Path(job.target).write_bytes(b'encoded')
        self.patches = [patch.object(texture_encode, 'encode_staged', encode),
                        patch.object(texture_encode, 'texconv_executable', return_value=Path('texconv.exe')),
                        patch.object(texture_encode, '_tool_identity', return_value='fake'),
                        patch.dict(os.environ, {texture_encode.SETTING: '', texture_encode.ENCODER_SETTING: ''})]
        for each in self.patches: each.start()
        self.executor = ThreadPoolExecutor(2)
        self.patches.append(patch.object(bake_pool, 'pool', return_value=self.executor)); self.patches[-1].start()

    def tearDown(self):
        self.release.set()
        for each in reversed(self.patches): each.stop()
        self.executor.shutdown()

    def image(self, value=1):
        return Image.new('RGBA', (64, 64), (value, 2, 3, 255))

    def test_conversions_continue_while_textures_compress_and_tickets_mark_completion(self):
        with tempfile.TemporaryDirectory() as t:
            with bake_pool.deferred_encodes():
                with bake_pool.Bakes() as first:
                    first(Path(t) / 'a_diff.dds', self.image(1), ET.Element('Material'))
                ticket = first.ticket()
                self.assertFalse(ticket.done())                      # wait() did not block on texconv
                self.assertFalse((Path(t) / 'a_diff.dds').exists())
                self.release.set()
                ticket.result(timeout=5)
                self.assertEqual((Path(t) / 'a_diff.dds').read_bytes(), b'encoded')
                with bake_pool.Bakes(encode_now=True) as second:     # e.g. coverage reads the result
                    second(Path(t) / 'b_diff.dds', self.image(2), ET.Element('Material'))
                self.assertEqual((Path(t) / 'b_diff.dds').read_bytes(), b'encoded')
                with bake_pool.Bakes() as third:
                    third(Path(t) / 'c_diff.dds', self.image(3), ET.Element('Material'))
            self.assertEqual((Path(t) / 'c_diff.dds').read_bytes(), b'encoded')   # leaving writes the rest
            self.assertIsNone(bake_pool._SHARED)

    def test_encode_errors_reach_the_ticket_and_the_scope(self):
        self.release.set()
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(RuntimeError, 'bad_diff.dds'):
                with bake_pool.deferred_encodes():
                    with bake_pool.Bakes() as bakes:
                        bakes(Path(t) / 'bad_diff.dds', self.image(), ET.Element('Material'))
                    with self.assertRaisesRegex(ValueError, 'bad_diff.dds'):
                        bakes.ticket().result(timeout=5)
            self.assertIsNone(bake_pool._SHARED)

    def test_outside_a_scope_bakes_write_everything_before_returning(self):
        self.release.set()
        with tempfile.TemporaryDirectory() as t:
            with bake_pool.Bakes() as bakes:
                bakes(Path(t) / 'a_diff.dds', self.image(), ET.Element('Material'))
            self.assertEqual((Path(t) / 'a_diff.dds').read_bytes(), b'encoded')
            self.assertTrue(bakes.ticket().done())


class StagedReuseTests(unittest.TestCase):
    """Identical bakes are reused while BC7 textures wait for texconv, as for float bakes."""
    def setUp(self):
        import os
        import texture_encode
        self.written = []
        def encode(jobs, executable, write=True):
            for job in jobs:
                self.written.append(Path(job.target).name)
                Path(job.target).write_bytes(b'encoded ' + Path(job.source).name.encode())
        self.patches = [patch.object(texture_encode, 'encode_staged', encode),
                        patch.object(texture_encode, 'texconv_executable', return_value=Path('texconv.exe')),
                        patch.object(texture_encode, '_tool_identity', return_value='fake'),
                        patch.dict(os.environ, {texture_encode.SETTING: '', texture_encode.ENCODER_SETTING: ''})]
        for each in self.patches: each.start()
        self.executor = ThreadPoolExecutor(2)
        self.patches.append(patch.object(bake_pool, 'pool', return_value=self.executor)); self.patches[-1].start()
        self.cache = bake_pool.TextureBakeCache()
        self.patches.append(patch.object(bake_pool, 'shared_cache', return_value=self.cache)); self.patches[-1].start()

    def tearDown(self):
        for each in reversed(self.patches): each.stop()
        self.executor.shutdown()
        self.cache.close()

    def test_identical_bakes_in_one_conversion_are_baked_once_and_each_path_is_written(self):
        image = Image.new('RGBA', (64, 64), (100, 200, 80, 255))
        with tempfile.TemporaryDirectory() as t, \
                patch.object(bake_pool, 'bake_float_dds', wraps=bake_pool.bake_float_dds) as bake:
            with bake_pool.Bakes(reuse=True) as bakes:
                bakes.plan(3)
                for i in range(3):
                    bakes(Path(t) / f'{i}_diff.dds', image, ET.Element('Material'))
            self.assertEqual(bake.call_count, 1)
            self.assertEqual(sorted(self.written), ['0_diff.dds', '1_diff.dds', '2_diff.dds'])
            self.assertEqual(len({p.read_bytes() for p in Path(t).iterdir()}), 1)
            self.assertEqual(bakes.stats, dict(completed=3, total=3, reused=2))

    def test_encoded_textures_reach_the_reuse_cache_for_the_next_conversion(self):
        image = Image.new('RGBA', (64, 64), (100, 200, 80, 255))
        with tempfile.TemporaryDirectory() as t, \
                patch.object(bake_pool, 'bake_float_dds', wraps=bake_pool.bake_float_dds) as bake:
            with bake_pool.Bakes(reuse=True) as first:
                first(Path(t) / 'a_diff.dds', image, ET.Element('Material'))
            self.assertEqual(len(self.cache.entries), 1)
            with bake_pool.Bakes(reuse=True) as second:
                second(Path(t) / 'b_diff.dds', image, ET.Element('Material'))
            self.assertEqual(bake.call_count, 1)
            self.assertEqual(self.written, ['a_diff.dds'])               # b is a copy of the cached file
            self.assertEqual((Path(t) / 'b_diff.dds').read_bytes(), (Path(t) / 'a_diff.dds').read_bytes())
            self.assertEqual(second.stats['reused'], 1)

    def test_deferred_conversions_offer_their_textures_to_the_cache_once_written(self):
        image = Image.new('RGBA', (64, 64), (100, 200, 80, 255))
        with tempfile.TemporaryDirectory() as t:
            with bake_pool.deferred_encodes():
                with bake_pool.Bakes(reuse=True) as first:
                    first(Path(t) / 'a_diff.dds', image, ET.Element('Material'))
                first.ticket().result(timeout=5)
            for _ in range(100):               # the offer runs on the encoder thread, just after the ticket
                if self.cache.entries: break
                time.sleep(0.02)
            self.assertEqual(len(self.cache.entries), 1)
