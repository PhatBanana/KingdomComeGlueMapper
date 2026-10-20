"""The diagnostic must not fix, suppress or reorder the lifecycle it observes."""
import sys
from pathlib import Path
import unittest

from lupa import LuaRuntime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from npc_initialization_trace import patch, RUNTIME


class NpcInitializationTraceTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
            logs={}; calls=0; actor={id=42,name="mother"}
            System={LogAlways=function(s) table.insert(logs,s) end}
            CryAction={HasAI=function(id) return calls>0 end}
            Native={Init=function(self, ...)
                calls=calls+1; return select("#", ...), ...
            end}
        ''')
        self.hook = RUNTIME.replace("__SELECTED__", '{mother=true}')
        self.lua.execute(self.hook)
        self.lua.execute('GlueMapperNpcInitTrace.wrap(Native,"Init","Native.Init")')

    def test_arguments_and_nil_returns_preserved(self):
        self.assertEqual(self.lua.eval('Native.Init(actor, nil, 8, nil)'), (3, None, 8, None))
        logs = self.lua.eval('table.concat(logs,"\\n")')
        self.assertIn("enter Native.Init call=1 name=mother id=42 hasAI=false", logs)
        self.assertIn("exit Native.Init call=1 name=mother id=42 hasAI=true", logs)

    def test_logging_failure_does_not_block_native(self):
        self.lua.execute('System.LogAlways=function() error("logger unavailable") end')
        self.assertEqual(self.lua.eval('Native.Init(actor, 7)'), (1, 7))
        self.assertEqual(self.lua.eval("calls"), 1)

    def test_native_errors_remain_errors_without_fake_exit(self):
        self.lua.execute('''
            Native.Fail=function() error("native init failed") end
            GlueMapperNpcInitTrace.wrap(Native,"Fail","Native.Fail")
        ''')
        ok, error = self.lua.eval('pcall(Native.Fail,actor)')
        self.assertFalse(ok)
        self.assertIn("native init failed", error)
        logs = self.lua.eval('table.concat(logs,"\\n")')
        self.assertIn("enter Native.Fail", logs)
        self.assertNotIn("exit Native.Fail", logs)

    def test_native_yield_preserved(self):
        self.lua.execute('''
            Native.Yield=function() coroutine.yield("waiting"); return "done" end
            GlueMapperNpcInitTrace.wrap(Native,"Yield","Native.Yield")
            co=coroutine.create(function() return Native.Yield(actor) end)
        ''')
        self.assertEqual(self.lua.eval("coroutine.resume(co)"), (True, "waiting"))
        self.assertEqual(self.lua.eval("coroutine.resume(co)"), (True, "done"))

    def test_reinstall_does_not_double_wrap(self):
        self.lua.execute(self.hook)
        self.lua.execute('GlueMapperNpcInitTrace.wrap(Native,"Init","Native.Init")')
        self.lua.eval("Native.Init(actor)")
        self.assertEqual(self.lua.eval("#logs"), 3)
        self.assertEqual(self.lua.eval("calls"), 1)

    def test_trace_is_filtered_and_bounded_without_skipping_calls(self):
        self.lua.execute('for i=1,20 do Native.Init(actor) end')
        self.assertEqual(self.lua.eval("#logs"), 9)
        self.assertEqual(self.lua.eval("calls"), 20)
        self.lua.execute('Native.Init({id=43,name="other"})')
        self.assertEqual(self.lua.eval("#logs"), 9)
        self.assertEqual(self.lua.eval("calls"), 21)

    def test_patch_requires_native_script_and_is_appended(self):
        path = "Scripts/Entities/AI/Shared/BasicAI.lua"
        original = b"function BasicAI:RegisterAI() end\n"
        result = patch(original, path, ["mother"])
        self.assertTrue(result.startswith(original))
        self.assertIn(b'wrap(BasicAI.Server, "OnInit"', result)
        with self.assertRaisesRegex(ValueError, "already present"):
            patch(result, path, ["mother"])
        with self.assertRaisesRegex(ValueError, "complete native"):
            patch(b"", path, ["mother"])
        with self.assertRaisesRegex(ValueError, "explicit NPC names"):
            patch(original, path, ['unsafe"'])


if __name__ == "__main__":
    unittest.main()
