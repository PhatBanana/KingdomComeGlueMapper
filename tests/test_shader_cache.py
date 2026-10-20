"""Compiled shader packages are reused across jobs only for identical signed inputs."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import setup_shaders
from shader_fixture import package_shaders


class ShaderCacheTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        reference = self.base/'reference'; reference.mkdir()
        package_shaders(reference)
        changes = json.loads((reference/'shader-build.json').read_text())['changes']
        self.signature = dict(source='a'*64, compiler='b'*64, changes=changes, tools={'Tools/rc/rc.exe': 'c'*64})
        self.compiles = 0

    def fake_prepare(self, target, output):
        root = Path(output)/'compiler'; root.mkdir(parents=True, exist_ok=True)
        return root, dict(self.signature)

    def fake_run(self, command, root, log, cancelled, notify, *, compiler_log=None):
        if compiler_log is not None:
            self.compiles += 1
            compiler_log.write_text('Combinations: (Material: 1, Processed: 1; Compiled: 1; Removed: 0)')
        else:
            package = Path(next(a for a in command if a.startswith('/OutputPath=')).split('=', 1)[1])
            package.mkdir(parents=True, exist_ok=True)
            package_shaders(package)

    def build(self, name, cache=True):
        environment = {'GLUEMAPPER_SHADER_CACHE': str(self.base/'cache')} if cache else {}
        with patch.object(setup_shaders, 'prepare', self.fake_prepare), \
             patch.object(setup_shaders, 'run_command', self.fake_run), \
             patch.dict(os.environ, environment):
            if not cache: os.environ.pop('GLUEMAPPER_SHADER_CACHE', None)
            return setup_shaders.build(self.base/'target', self.base/name)

    def test_identical_inputs_reuse_the_compiled_package(self):
        self.build('first')
        self.build('second')
        self.assertEqual(self.compiles, 1)
        for name in setup_shaders.ARCHIVES:
            self.assertEqual((self.base/'first/package/Engine'/name).read_bytes(),
                             (self.base/'second/package/Engine'/name).read_bytes())

    def test_changed_inputs_or_damaged_entries_compile_again(self):
        self.build('first')
        self.signature['tools'] = {'Tools/rc/rc.exe': 'd'*64}
        self.build('second')
        self.assertEqual(self.compiles, 2)
        with patch.dict(os.environ, {'GLUEMAPPER_SHADER_CACHE': str(self.base/'cache')}):
            entry = setup_shaders.cache_entry(self.signature)
        (entry/'Engine/ShaderCache.pak').write_bytes(b'damaged')
        self.build('third')
        self.assertEqual(self.compiles, 3)

    def test_without_a_cache_every_build_compiles(self):
        self.build('one', cache=False)
        self.build('two', cache=False)
        self.assertEqual(self.compiles, 2)


if __name__ == '__main__':
    unittest.main()
