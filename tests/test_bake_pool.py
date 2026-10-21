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
