import sys
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from setup_shaders import REPAIRS, patched, validate, compilation_result, run_command, _LiveLog
from shader_fixture import package_shaders


class ShaderSetupTests(unittest.TestCase):
    def test_compiler_output_reaches_application_events_before_process_exits(self):
        from desktop_setup import EventLog, LogWriter
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            native = root/'shadercachegen.log'
            native.write_text('stale previous compilation\n')
            events = EventLog(root/'events.jsonl')
            observed = []
            script = ("from pathlib import Path; import time; "
                      "p=Path('shadercachegen.log'); p.write_text('Compiling shader 1\\n'); "
                      "time.sleep(2.2); p.open('a').write('Finished without newline')")
            try:
                with redirect_stdout(LogWriter(events)):
                    run_command([sys.executable, '-c', script], root, root/'compile.log',
                                lambda: False,
                                lambda *args: observed.append((root/'setup.log').read_text()),
                                compiler_log=native)
                self.assertTrue(any('Compiling shader 1' in text for text in observed))
                messages = [json.loads(line).get('message', '') for line in
                            (root/'events.jsonl').read_text().splitlines()]
                self.assertEqual(messages.count('Compiling shader 1'), 1)
                self.assertIn('Finished without newline', messages)
                self.assertNotIn('stale previous compilation', '\n'.join(messages))
            finally:
                events.stream.close(); events.text.close()

    def test_live_log_partial_utf8_and_truncation(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'native.log'; live = _LiveLog(path)
            output = io.StringIO()
            with redirect_stdout(output):
                live.drain()
                path.write_bytes(b'compile caf\xc3'); live.drain()
                self.assertEqual(output.getvalue(), '')
                with path.open('ab') as stream: stream.write(b'\xa9\r\n')
                live.drain(); live.drain()
                path.write_bytes(b'end'); live.drain(final=True)
            self.assertEqual(output.getvalue(), 'compile café\nend\n')

    def test_failure_and_cancellation_flush_native_output(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); native = root/'shadercachegen.log'
            for cancelled, script, error in (
                (lambda: False, "import sys; sys.exit(7)", ValueError),
                (lambda: True, "import time; time.sleep(30)", InterruptedError),
            ):
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaises(error):
                    run_command([sys.executable, '-c',
                        "from pathlib import Path; Path('shadercachegen.log').write_text('last diagnostic'); " + script],
                        root, root/'compile.log', cancelled, lambda *a: None, compiler_log=native)
                self.assertIn('last diagnostic', output.getvalue())

    def test_repairs_rebuild_against_previous_install_and_reject_unknown_source(self):
        for name, pair in REPAIRS.items():
            result = patched(name,pair[0])
            self.assertEqual(result,pair[1])
            self.assertEqual(patched(name,result),result)
            with self.assertRaises(ValueError): patched(name,b'unknown native shader')

    def test_compiler_exit_without_success_summary_or_with_errors_is_not_success(self):
        summary='Combinations: (Material: 20, Processed: 31; Compiled: 30; Removed: 5)'
        self.assertEqual(compilation_result(summary)['compiled'],30)
        for log in ('', summary+'\nerror X3000: invalid conversion', summary+'\nShader compile failed'):
            with self.assertRaises(ValueError): compilation_result(log)

    def test_compiled_package_is_explicitly_build_only(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); package=root/'package'; package.mkdir(); package_shaders(package)
            report=validate(package)
            self.assertEqual(report['installation'],'build_only')
            self.assertFalse(report['isolated_mount_verified'])
            self.assertFalse(report['runtime_verified'])

    def test_tampered_package_does_not_change_game(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); package=root/'package'; package.mkdir(); package_shaders(package)
            self.assertEqual(validate(package)['repairs'],3)
            (package/'Engine/ShaderCache.pak').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'changed'): validate(package)
            self.assertFalse((root/'target').exists())


if __name__=='__main__': unittest.main()
