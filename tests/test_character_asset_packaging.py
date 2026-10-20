from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_quest_people_test import write_actor_paks
from texture_streaming import layout, split_generated, validate_family
from test_texture_streaming import texture


class CharacterAssetPackagingTests(unittest.TestCase):
    def package(self, root, files, limit=900*1024**2):
        appearance, data = root/'appearance', root/'Data'
        data.mkdir()
        for name, blob in files.items():
            p = appearance/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(blob)
        with patch.dict(os.environ, {}, clear=True):
            paks, libs = write_actor_paks(appearance, data, 'actor', limit)
        entries = {}
        for p in paks:
            self.assertLessEqual(p.stat().st_size, limit)
            with zipfile.ZipFile(p) as z:
                self.assertIsNone(z.testzip())
                for n in z.namelist():
                    self.assertNotIn(n, entries)
                    entries[n] = z.read(n)
        return entries, libs, paks

    def test_float_macro_is_streamed_across_shards_without_pixel_changes(self):
        name = 'objects/characters/test/native_diff.dds'
        blob = texture(512, 512, 10)
        with tempfile.TemporaryDirectory() as tmp:
            files, libs, paks = self.package(Path(tmp), {
                name: blob, 'objects/characters/test/body.skin': b'skin untouched',
                'objects/characters/test/body.mtl': b'<Material/>',
                'Libs/Tables/Character/actor.xml': b'<database/>'}, 2100000)
        parts = {k[len(name):]: v for k, v in files.items() if k.startswith(name)}
        state = validate_family(parts[''], parts)
        self.assertGreater(len(paks), 1)
        self.assertGreater(state['streamed_mips'], 0)
        self.assertLess(len(parts['']), 4096)
        joined = b''.join(parts['.'+str(i)] for i in range(state['streamed_mips'], 0, -1)) + parts[''][148:]
        self.assertEqual(joined, blob[148:148+sum(layout(parts[''])['sizes'])])
        self.assertEqual(files['objects/characters/test/body.skin'], b'skin untouched')
        self.assertEqual(files['objects/characters/test/body.mtl'], b'<Material/>')
        self.assertEqual(libs, {'Libs/Tables/Character/actor.xml': b'<database/>'})

    def test_existing_split_family_is_not_split_again(self):
        family = split_generated(texture(512, 512, 10))
        incoming = {'objects/character.dds'+k: v for k, v in family.items()}
        with tempfile.TemporaryDirectory() as tmp:
            files, _, _ = self.package(Path(tmp), incoming)
        self.assertEqual(files, incoming)

    def test_generated_mask_gains_mips_without_changing_full_resolution_pixels(self):
        import io
        from PIL import Image
        stream=io.BytesIO()
        Image.new('RGBA',(1024,1024),(11,22,33,255)).save(stream,format='DDS')
        blob=stream.getvalue(); name='objects/character_mask.dds'
        with tempfile.TemporaryDirectory() as tmp:
            files, _, _ = self.package(Path(tmp),{name:blob})
        parts={k[len(name):]:v for k,v in files.items()}
        result=validate_family(parts[''],parts)
        self.assertEqual(parts['.'+str(result['streamed_mips'])],blob[128:])
        self.assertLess(len(parts['']),4096)

    def test_missing_streamed_slice_cannot_be_packaged(self):
        family = split_generated(texture(512, 512, 10))
        del family['.1']
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'Missing texture mip'):
                self.package(Path(tmp), {'objects/character.dds'+k: v for k,v in family.items()})

    def test_truncated_generated_texture_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'complete DDS mip chain'):
                self.package(Path(tmp), {'objects/character.dds': texture(512,512,10)[:-1]})

    def test_opening_scene_uses_same_streaming_layout_and_keeps_library_resources(self):
        from campaign_scene_test import appearance_resources
        with tempfile.TemporaryDirectory() as tmp:
            appearance=Path(tmp)
            (appearance/'objects').mkdir(); (appearance/'Libs').mkdir()
            blob=texture(512,512,10)
            (appearance/'objects/skin.dds').write_bytes(blob)
            (appearance/'Libs/component.xml').write_bytes(b'<database/>')
            with patch.dict(os.environ, {}, clear=True):
                result=appearance_resources(appearance)
            expected={'objects/skin.dds'+suffix: data for suffix,data in split_generated(blob).items()}
            expected['Libs/component.xml']=b'<database/>'
            self.assertEqual(result, expected)


if __name__ == '__main__': unittest.main()
