import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

from lupa import LuaRuntime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_intro_activity import emit, plan
from test_campaign_intro_initialization import source
from trace_campaign_intro import build, instrument, lua_log


def fixture():
    report = dict(placement=dict(quest='example', actor_guid='12345678-abcd-1234'),
                  source_plan=plan(E.tostring(source()), 'intro'))
    path = 'AI/gm_intro_example_intro.xml'
    return report, path, emit('gm_intro_example_intro', report['source_plan'])[path]


def shape(node):
    return node.tag, node.attrib, [shape(c) for c in node]


def strip_trace(node):
    if node.tag in ('ExecuteLua', 'IsFastForwarded'):
        return None
    if node.tag == 'LuaWrapper':
        return strip_trace(node[0])
    if (node.tag == 'FuseBox' and node.find('OnSuccess/Sequence/ExecuteLua') is not None
            and 'event=bark_branch_success' in node.find('OnSuccess/Sequence/ExecuteLua').get('code')):
        return strip_trace(node.find('Child')[0])
    diagnostic_prefix = len(node) and node[0].tag in ('ExecuteLua', 'IsFastForwarded')
    children = [strip_trace(c) for c in node]
    node[:] = [c for c in children if c is not None]
    if node.tag == 'Sequence' and diagnostic_prefix and len(node) == 1:
        return node[0]
    return node


class IntroTraceTests(unittest.TestCase):
    def test_preparation_acknowledgement_and_custom_event_set_are_preserved(self):
        from campaign_intro_preparation import CONTEXT
        report, path, _ = fixture()
        report['source_plan']['temporary_faction'] = dict(preparation=dict(
            version=1, native_context=CONTEXT,
            release='worker_initialization_acknowledgement', scope='eligible_intro_uninitialized'))
        blob = emit('gm_intro_example_intro', report['source_plan'])[path]
        root = E.fromstring(instrument(blob, report)[1])
        ack = root.find("BehaviorTree/Root/OnInit/Sequence/Callback_empty")
        self.assertEqual(ack.get('EventName'), "'Initialized'")
        self.assertEqual(shape(strip_trace(root)), shape(E.fromstring(blob)))

    def test_original_graph_recovered_exactly_when_logs_removed(self):
        report, path, blob = fixture()
        name, result = instrument(blob, report)
        self.assertEqual(name, path)
        root = E.fromstring(result)
        self.assertEqual(len(root.findall('.//LuaWrapper')), 1)
        root = strip_trace(root)
        self.assertEqual(shape(root), shape(E.fromstring(blob)))
        original = E.fromstring(blob)
        self.assertEqual([n.attrib for n in root.iter('Wait')], [n.attrib for n in original.iter('Wait')])

    def test_branch_result_trace_preserves_result_and_child_order(self):
        report, _, blob = fixture()
        root = E.fromstring(instrument(blob, report)[1])
        body = root.find('BehaviorTree/Root/Behavior/Sequence')
        self.assertIn('event=body_enter', body[0].get('code'))
        parallel = body.find('FuseBox/Child/Parallel')
        self.assertIn('event=bark_branch_enter', parallel[0][0].get('code'))
        self.assertIn('event=seat_branch_enter', parallel[1][0].get('code'))
        self.assertEqual(parallel[1][1].tag, 'EntityContextElement')
        fuse = parallel[0][1]
        self.assertEqual(fuse.get('StatusPropagation'), 'Child')
        self.assertEqual(fuse.find('Child')[0].tag, 'DistanceGate')
        for branch, result in (('OnSuccess', 'Success'), ('OnFail', 'Fail')):
            seq = fuse.find(branch+'/Sequence')
            self.assertEqual([n.tag for n in seq], ['ExecuteLua', result])
            lua = self.lua()
            lua.execute('System=nil')
            lua.execute(seq[0].get('code'))
            self.assertEqual(seq[1].tag, result)
        gate_child = fuse.find('Child/DistanceGate/Sequence')
        self.assertIn('event=distance_gate_child_enter', gate_child[0].get('code'))
        self.assertIn('event=dialog_gate_child_enter', gate_child.find('DialogGate/Sequence/ExecuteLua').get('code'))

    def test_native_mode_checks_are_immediate_and_do_not_gate_game_child(self):
        report, _, blob = fixture()
        root = E.fromstring(instrument(blob, report)[1])
        checks = root.findall('.//IsFastForwarded')
        self.assertEqual(len(checks), 2)
        for check in checks:
            self.assertEqual(check.attrib, dict(failOnCondition='false', saveVersion='2'))
            self.assertEqual([n.tag for n in check], ['Then', 'Else'])
            for branch in check:
                self.assertEqual([n.tag for n in branch[0]], ['ExecuteLua', 'Success'])
                lua = self.lua()
                lua.execute('System=nil')
                lua.execute(branch[0][0].get('code'))
                self.assertEqual(branch[0][-1].tag, 'Success')
        seat = root.find('.//LuaWrapper/Sequence')
        self.assertEqual([n.tag for n in seat], ['IsFastForwarded', 'CallBehavior'])
        self.assertEqual(seat[-1].get('Target'), '$workPlace')

    def test_first_entry_event_stays_inside_persistent_guard(self):
        report, _, blob = fixture()
        root = E.fromstring(instrument(blob, report)[1])
        first = root.find('.//OnInit/Sequence/IfCondition/Sequence')
        self.assertIn('first_entry_complete', first[-1].get('code'))
        self.assertEqual(first[-2].tag, 'LogToConsole')
        self.assertEqual(root.find('.//IfCondition').get('condition'), '$firstPhase < 7')

    def test_unknown_or_already_instrumented_worker_fails_closed(self):
        report, _, blob = fixture()
        changed = blob.replace(b'$workPlace', b'$otherPlace')
        for bad in (changed, instrument(blob, report)[1]):
            with self.assertRaisesRegex(ValueError, 'differs'):
                instrument(bad, report)
        for limit in (0, 101, True, 1.5):
            with self.assertRaises(ValueError): instrument(blob, report, limit)

    def test_separate_output_and_input_byte_preservation(self):
        report, path, blob = fixture()
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'package'
            (package / 'Data').mkdir(parents=True)
            (package / 'quest-introductions.json').write_text(json.dumps(report))
            with zipfile.ZipFile(package / 'Data/gluemappertravel.pak', 'w') as z:
                z.writestr(path, blob)
                z.writestr('unrelated', b'preserve')
            before = {str(p): p.read_bytes() for p in package.rglob('*') if p.is_file()}
            output = Path(temp) / 'trace'
            with patch('campaign_combat_work.validate') as validator:
                result = build(package, output, Path(temp) / 'native')
            self.assertFalse(result['installed'])
            self.assertEqual(list(validator.call_args.args[0]), [path])
            self.assertEqual(before, {str(p): p.read_bytes() for p in package.rglob('*') if p.is_file()})
            with zipfile.ZipFile(output / 'intro-trace.pak') as z:
                self.assertEqual(z.namelist(), [path])
            with self.assertRaisesRegex(ValueError, 'already exists'): build(package, output, temp)
            with self.assertRaisesRegex(ValueError, 'separate'): build(package, package / 'trace', temp)
            failed = Path(temp) / 'failed'
            with patch('campaign_combat_work.validate', side_effect=ValueError('unsupported native graph')):
                with self.assertRaisesRegex(ValueError, 'unsupported'): build(package, failed, temp)
            self.assertFalse(failed.exists())

    def lua(self):
        lua = LuaRuntime()
        lua.execute('''
          logs={}; actor={id=42}; entity=actor; data={this={id=42}}
          function actor:GetWorldPos(p) p.x=1; p.y=2; p.z=3 end
          XGenAIModule={GetEntityByWUID=function(id) return actor end}
          AI={GetFactionOf=function(id) return "Civilians" end}
          actor.soul={GetFactionID=function() return 7 end}
          Calendar={GetWorldTime=function() return 36000 end, GetWorldHourOfDay=function() return 10 end}
          System={LogAlways=function(s) table.insert(logs,s) end}
        ''')
        return lua

    def test_lua_uses_actual_values_and_bounds_each_entity_event(self):
        lua = self.lua()
        code = lua_log('worker', '12345678-abcd-1234', 'seat_enter', 2)
        for _ in range(10): lua.execute(code)
        self.assertEqual(lua.eval('#logs'), 2)
        self.assertIn('pos=1,2,3 faction=Civilians', lua.eval('logs[1]'))
        self.assertIn('soul_faction_id=7', lua.eval('logs[1]'))
        self.assertIn('world_time=36000 world_hour=10', lua.eval('logs[1]'))
        lua.execute(lua_log('worker', '12345678-abcd-1234', 'seat_exit', 2))
        self.assertEqual(lua.eval('#logs'), 3)

    def test_calendar_failure_retains_event_with_unknown_clock(self):
        lua = self.lua()
        lua.execute('Calendar=nil')
        lua.execute(lua_log('worker', '12345678-abcd-1234', 'initializer_enter', 2))
        self.assertEqual(lua.eval('#logs'), 1)
        self.assertIn('world_time=unavailable world_hour=unavailable', lua.eval('logs[1]'))

    def test_lua_missing_getters_and_logger_cannot_fail_worker(self):
        code = lua_log('worker', '12345678-abcd-1234', 'seat_enter', 2)
        for failure in ('AI=nil', 'actor.GetWorldPos=nil', 'System=nil',
                        'System.LogAlways=function() error("failure") end',
                        'entity=nil'):
            with self.subTest(failure=failure):
                lua = self.lua()
                lua.execute(failure)
                lua.execute(code + '\nnativeContinued=true')
                self.assertTrue(lua.eval('nativeContinued'))

    def test_each_native_node_uses_its_verified_context(self):
        lua = self.lua()
        lua.execute('data=nil; XGenAIModule=nil')
        lua.execute(lua_log('worker', '12345678-abcd-1234', 'initializer_enter', 2))
        self.assertEqual(lua.eval('#logs'), 1)
        lua = self.lua()
        lua.execute('data=nil; XGenAIModule=nil')
        lua.execute(lua_log('worker', '12345678-abcd-1234', 'seat_enter', 2, wrapper=True))
        self.assertEqual(lua.eval('#logs'), 1)
        self.assertIn('pos=1,2,3', lua.eval('logs[1]'))
        lua.execute('entity=nil')
        lua.execute(lua_log('worker', '12345678-abcd-1234', 'seat_exit', 2, wrapper=True))
        self.assertEqual(lua.eval('#logs'), 2)
        self.assertIn('context:', lua.eval('logs[2]'))

    def test_missing_context_events_are_bounded_and_getter_errors_visible(self):
        lua = self.lua()
        lua.execute('entity=nil')
        for _ in range(10):
            lua.execute(lua_log('worker', '12345678-abcd-1234', 'seat_enter', 2, wrapper=True))
        self.assertEqual(lua.eval('#logs'), 2)
        self.assertIn('entity context unavailable', lua.eval('logs[1]'))
        lua = self.lua()
        lua.execute('AI=nil')
        lua.execute(lua_log('worker', '12345678-abcd-1234', 'seat_enter', 2, wrapper=True))
        self.assertIn('faction=unavailable soul_faction_id=7', lua.eval('logs[1]'))
        self.assertIn('errors=faction:', lua.eval('logs[1]'))


if __name__ == '__main__':
    unittest.main()
