import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from blend_cache import cached_convert


def material():
    return ET.fromstring('<Material><Textures><Texture Map="[1] Diffuse" File="moss.dds"/>'
                         '<Texture Map="Opacity" File="mask.dds"/></Textures></Material>')


def fake_convert(doc, geometry, target, asset_read, index):
    textures = doc.find('Textures')
    textures.find("Texture[@Map='[1] Diffuse']").set('File', target+'_blend0_diff.dds')
    textures.remove(textures.find("Texture[@Map='Opacity']"))
    return geometry+b'-atlas', {target+'_blend0_diff.dds': b'DDS '+target.encode()}


class BlendCacheTests(unittest.TestCase):
    def test_hit_reproduces_bake_for_another_target(self):
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, {'GLUEMAPPER_BLEND_CACHE': cache}):
            fresh = material()
            geometry, baked = cached_convert(fake_convert, 'objects/a', fresh, b'mesh', 'g/m1', None, None)
            calls = []
            hit_doc = material()
            hit = cached_convert(lambda *a: calls.append(a), 'objects/a', hit_doc, b'mesh', 'g/m7', None, None)
            self.assertEqual(calls, [])
            self.assertEqual(hit[0], geometry)
            self.assertEqual(set(hit[1]), {'g/m7_blend0_diff.dds'})
            self.assertEqual(hit[1]['g/m7_blend0_diff.dds'], b'DDS g/m1')
            self.assertEqual(ET.tostring(hit_doc), ET.tostring(fresh).replace(b'g/m1', b'g/m7'))

    def test_different_geometry_or_material_misses(self):
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, {'GLUEMAPPER_BLEND_CACHE': cache}):
            cached_convert(fake_convert, 'objects/a', material(), b'mesh', 'g/m1', None, None)
            for name, geometry in (('objects/a', b'other mesh'), ('objects/b', b'mesh')):
                calls = []
                def counting(*a):
                    calls.append(1); return fake_convert(*a)
                cached_convert(counting, name, material(), geometry, 'g/m2', None, None)
                self.assertEqual(calls, [1])

    def test_unsupported_input_error_is_cached(self):
        def unsupported(*a):
            raise ValueError('Blend atlas requires float primary and secondary UV streams')
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, {'GLUEMAPPER_BLEND_CACHE': cache}):
            with self.assertRaisesRegex(ValueError, 'float primary'):
                cached_convert(unsupported, 'objects/a', material(), b'mesh', 'g/m1', None, None)
            with self.assertRaisesRegex(ValueError, 'float primary'):
                cached_convert(lambda *a: self.fail('should hit the cache'), 'objects/a', material(), b'mesh', 'g/m2', None, None)

    def test_disabled_cache_calls_converter_directly(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('GLUEMAPPER_BLEND_CACHE', None)
            doc = material()
            self.assertEqual(cached_convert(fake_convert, 'objects/a', doc, b'mesh', 'g/m1', None, None)[0], b'mesh-atlas')


if __name__ == '__main__':
    unittest.main()
