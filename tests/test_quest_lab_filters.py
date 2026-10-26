import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.audit import audit, write
from quest_lab.filters import ActionTable
from quest_lab.gate_audit import audit_gates
from quest_lab.graph import Graph
from quest_lab.runner import Runner
from quest_lab.source import Source

# Synthetic subset of the retail input profile: same filter and action names, no retail bytes.
PROFILE = b'''<profile>
  <actionmap name="open_apse_keyboard">
    <action name="open_apse_inventory_keyboard"/><action name="open_apse_map_keyboard"/><action name="open_apse_codex"/>
  </actionmap>
  <actionmap name="open_apse_controller"><action name="open_apse_map_controller"/></actionmap>
  <actionmap name="player"><action name="use"/><action name="talk"/><action name="jump"/></actionmap>
  <actionfilter name="no_inventory">
    <action name="open_apse_inventory_keyboard"/><action name="open_apse_map_keyboard"/>
    <action name="open_apse_map_controller"/><action name="open_apse_codex"/>
  </actionfilter>
  <actionfilter name="no_interaction"><action name="use"/><action name="talk"/></actionfilter>
  <actionfilter name="no_move"><action name="jump"/></actionfilter>
</profile>'''

# The gate exactly as the arrival fix emits it: one native hold started by both Level events.
GATE = '''<Timer Name="arrival_ui_settle"><Constant Name="Duration" Value="90s"/><Constant Name="TimeType" Value="GameTime"/>
  <Edge From="OnWake" To="SetRunning"/><Edge From="OnLevelSwitched" To="SetRunning"/></Timer>
  <MakeArray Name="arrival_ui_filters" TypeT="Strings"><Constant Name="A" Value="no_inventory"/><Constant Name="B" Value="no_interaction"/></MakeArray>
  <FilterInput Name="arrival_ui_gate"><Edge From="arrival_ui_filters.Array" To="Filters"/>
  <Edge From="arrival_ui_settle.Running" To="IsActive"/></FilterInput>'''

MAP = 'open_apse_map_keyboard'


def level(nodes, name='L', tag='Level', ports=''):
    return ('<Database><Skald><' + tag + ' Name="' + name + '"><Ports>' + ports + '</Ports><Nodes>' + nodes +
            '</Nodes></' + tag + '></Skald></Database>').encode()


def source(nodes, **kwargs):
    return Source.blobs({'level.xml': level(nodes, **kwargs)})


def graph(nodes=GATE, table=True, **kwargs):
    return Graph(source(nodes, **kwargs), kwargs.get('name', 'L'), actions=ActionTable(PROFILE) if table else None)


def run(steps, nodes=GATE, **extra):
    s = dict(schema=1, name='gate', entry='L', steps=steps, **extra)
    with tempfile.TemporaryDirectory() as temp:
        (Path(temp) / 'profile.xml').write_bytes(PROFILE)
        s.setdefault('action_profile', 'profile.xml')
        return Runner(s, base=Path(temp), source=source(nodes)).run()


class GateModelTests(unittest.TestCase):
    def test_gate_is_interpreted_and_idle_until_an_entry_event(self):
        g = graph()
        self.assertEqual(g.unsupported, [])
        self.assertEqual(g.active_filters(), [])
        self.assertEqual(g.action_state(MAP), 'allowed')
        self.assertFalse(g.value('arrival_ui_settle.Running'))

    def test_hold_covers_map_inventory_and_interaction_then_releases_at_the_deadline(self):
        for event in ('OnWake', 'OnLevelSwitched'):
            with self.subTest(event=event):
                g = graph()
                g.fire(event)
                self.assertTrue(g.value('arrival_ui_settle.Running'))
                self.assertEqual(g.active_filters(), ['no_interaction', 'no_inventory'])
                for action in (MAP, 'open_apse_map_controller', 'open_apse_inventory_keyboard', 'use', 'talk'):
                    self.assertEqual(g.action_state(action), 'blocked', action)
                self.assertEqual(g.action_state('jump'), 'allowed')
                g.advance_to(89999999); self.assertEqual(g.action_state(MAP), 'blocked')
                g.advance_to(90000000)
                self.assertEqual(g.action_state(MAP), 'allowed')
                self.assertEqual(g.active_filters(), [])
                self.assertEqual([r['active'] for r in g.trace if r['kind'] == 'filters'],
                                 [[], ['no_interaction', 'no_inventory'], []])

    def test_second_entry_event_restarts_the_hold_under_emulator_semantics(self):
        g = graph()
        g.fire('OnWake'); g.advance_to(60000000); g.fire('OnLevelSwitched')
        g.advance_to(120000000); self.assertEqual(g.action_state(MAP), 'blocked')
        g.advance_to(150000000); self.assertEqual(g.action_state(MAP), 'allowed')

    def test_save_and_restore_preserve_a_partial_hold(self):
        g = graph()
        g.fire('OnWake'); g.advance_to(30000000)
        saved = g.snapshot()
        g.advance_to(100000000); self.assertEqual(g.action_state(MAP), 'allowed')
        g.restore(saved)
        self.assertEqual(g.action_state(MAP), 'blocked')
        g.advance_to(g.now + 59999999); self.assertEqual(g.action_state(MAP), 'blocked')
        g.advance_to(g.now + 1); self.assertEqual(g.action_state(MAP), 'allowed')

    def test_active_set_is_the_union_of_active_nodes(self):
        nodes = GATE + '''<State Name="move_hold" TypeT="bool"><Constant Name="DefaultValue" Value="false"/>
          <Edge From="OnWake" To="SetTrue"/><Edge From="OnLevelSwitched" To="SetFalse"/></State>
          <MakeArray Name="move_filters" TypeT="Strings"><Constant Name="A" Value="no_move"/></MakeArray>
          <FilterInput Name="move_gate"><Edge From="move_filters.Array" To="Filters"/>
          <Edge From="move_hold.State" To="IsActive"/></FilterInput>'''
        g = graph(nodes)
        self.assertEqual(g.unsupported, [])
        g.fire('OnWake'); self.assertEqual(g.active_filters(), ['no_interaction', 'no_inventory', 'no_move'])
        g.advance_to(90000000)
        self.assertEqual(g.active_filters(), ['no_move'])
        self.assertEqual((g.action_state(MAP), g.action_state('jump')), ('allowed', 'blocked'))
        g.fire('OnLevelSwitched')  # restarts the timer and clears the move hold
        self.assertEqual((g.action_state(MAP), g.action_state('jump')), ('blocked', 'allowed'))
        g.advance_to(g.now + 90000000)
        self.assertEqual(g.active_filters(), [])

    def test_timer_running_is_false_after_stop(self):
        stop = GATE.replace('<Edge From="OnLevelSwitched" To="SetRunning"/>', '<Edge From="OnLevelSwitched" To="SetStopped"/>')
        g = graph(stop)
        g.fire('OnWake'); self.assertEqual(g.action_state(MAP), 'blocked')
        g.fire('OnLevelSwitched'); self.assertEqual(g.action_state(MAP), 'allowed')

    def test_unknown_action_and_filter_are_not_guessed(self):
        g = graph()
        with self.assertRaises(ValueError): g.action_state('open_apse_typo')
        bad = graph(GATE.replace('no_interaction', 'no_such_filter'))
        bad.fire('OnWake')
        with self.assertRaises(Unsupported): bad.action_state(MAP)
        self.assertTrue(any('Filter state is not evaluable' in u['reason'] for u in bad.unsupported))

    def test_missing_table_or_inputs_are_unsupported_not_open_gates(self):
        g = graph(table=False)
        self.assertTrue(any('table not supplied' in u['reason'] for u in g.unsupported))
        with self.assertRaises(Unsupported): g.action_state(MAP)
        partial = graph('''<FilterInput Name="g"><Constant Name="IsActive" Value="true"/></FilterInput>''')
        self.assertTrue(any('Missing explicit value input: Filters' in u['reason'] for u in partial.unsupported))
        extra = graph(GATE.replace('<FilterInput Name="arrival_ui_gate">', '<FilterInput Name="arrival_ui_gate"><Constant Name="Mode" Value="x"/>'))
        self.assertTrue(any('Unsupported input: Mode' in u['reason'] for u in extra.unsupported))

    def test_is_active_must_be_boolean(self):
        g = graph('''<MakeArray Name="f" TypeT="Strings"><Constant Name="A" Value="no_move"/></MakeArray>
          <FilterInput Name="g"><Edge From="f.Array" To="Filters"/><Constant Name="IsActive" Value="1"/></FilterInput>''')
        with self.assertRaises(Unsupported): g.active_filters()

    def test_engine_events_exist_only_on_levels_and_must_be_fired_explicitly(self):
        module = Graph(source(GATE, tag='Module'), 'L', actions=ActionTable(PROFILE))
        self.assertNotIn('OnWake', module.event_ports)
        self.assertTrue(module.unsupported)
        g = graph()
        self.assertEqual(g.engine_fired['OnWake'], 0)
        g.fire('OnWake')
        self.assertEqual([r['boundary'] for r in g.trace if r['kind'] == 'stimulus'], ['engine_event'])

    def test_profile_changes_invalidate_snapshots(self):
        a = graph(); b = Graph(source(GATE), 'L', actions=ActionTable(PROFILE.replace(b'"talk"', b'"talk2"', 1)))
        self.assertNotEqual(a.fingerprint, b.fingerprint)
        with self.assertRaises(ValueError): b.restore(a.snapshot())

    def test_profile_parser_rejects_duplicate_or_empty_filters(self):
        for blob in (b'<p><actionfilter name="a"><action name="x"/></actionfilter><actionfilter name="a"><action name="y"/></actionfilter></p>',
                     b'<p><actionfilter name="a"/></p>', b'<p/>'):
            with self.assertRaises(ValueError): ActionTable(blob)




class GateScenarioTests(unittest.TestCase):
    ARRIVE = [dict(action='assert_actions', actions={MAP: 'allowed'}, label='before the entry event'),
              dict(action='fire', port='OnWake'),
              dict(action='assert_actions', actions={MAP: 'blocked', 'use': 'blocked', 'jump': 'allowed'},
                   filters=['no_inventory', 'no_interaction'])]

    def test_arrival_scenario_passes_with_coverage_release_and_native_unknowns(self):
        r = run([*self.ARRIVE, dict(action='await_action', input=MAP, timeout='5m', at_least_game='90s'),
                 dict(action='assert_actions', actions={MAP: 'allowed', 'use': 'allowed'})])
        self.assertEqual(r['status'], 'PASS', r['error'])
        unknowns = {u['id']: u['status'] for u in r['filter_gate']['native_unknowns']}
        self.assertEqual(unknowns['onwake_on_save_load'], 'ASSUMED_BY_SCENARIO')
        self.assertEqual(unknowns['game_time_real_time_scale'], 'UNSUPPORTED')
        for key in ('ui_input_causes_freeze', 'scripted_paths_bypass_filters', 'node_port_names'):
            self.assertEqual(unknowns[key], 'UNSUPPORTED')
        self.assertEqual(r['filter_gate']['engine_events_fired'], {'OnWake': 1})
        self.assertFalse(r['native_runtime_verified'])

    def test_level_switch_alone_does_not_assume_onwake(self):
        r = run([dict(action='fire', port='OnLevelSwitched'), dict(action='assert_actions', actions={MAP: 'blocked'})])
        self.assertEqual(r['status'], 'PASS', r['error'])
        self.assertEqual({u['id']: u['status'] for u in r['filter_gate']['native_unknowns']}['onwake_on_save_load'], 'UNSUPPORTED')

    def test_real_time_claims_need_an_explicit_scale(self):
        steps = [*self.ARRIVE, dict(action='await_action', input=MAP, timeout='5m', at_least_real='60s')]
        self.assertEqual(run(steps)['status'], 'UNSUPPORTED')
        scale = lambda x: dict(real_seconds_per_game_second=x, reason='scenario assumption, not measured')
        passed = run(steps, time_scale=scale(1.0))
        self.assertEqual(passed['status'], 'PASS', passed['error'])
        self.assertEqual({u['id']: u['status'] for u in passed['filter_gate']['native_unknowns']}['game_time_real_time_scale'],
                         'ASSUMED_BY_SCENARIO')
        self.assertEqual(run(steps, time_scale=scale(0.1))['status'], 'FAIL')  # 90 GameTime s is only 9 real s

    def test_bad_time_scale_is_rejected(self):
        for bad in (dict(real_seconds_per_game_second=0, reason='x'), dict(real_seconds_per_game_second=True, reason='x'),
                    dict(real_seconds_per_game_second=1), 5):
            with self.subTest(bad=bad), self.assertRaises((ValueError, AttributeError, TypeError)):
                run(self.ARRIVE, time_scale=bad)

    def test_hold_that_is_too_short_fails(self):
        r = run([*self.ARRIVE, dict(action='await_action', input=MAP, timeout='5m', at_least_game='90s')],
                nodes=GATE.replace('90s', '5s'))
        self.assertEqual(r['status'], 'FAIL')

    def test_filter_leak_times_out(self):
        leak = GATE.replace('<Edge From="arrival_ui_settle.Running" To="IsActive"/>', '<Constant Name="IsActive" Value="true"/>')
        r = run([dict(action='assert_actions', actions={MAP: 'blocked'}),
                 dict(action='await_action', input=MAP, timeout='24h')], nodes=leak)
        self.assertEqual(r['status'], 'TIMEOUT')

    def test_without_a_profile_the_scenario_cannot_pass(self):
        s = dict(schema=1, name='gate', entry='L', steps=[dict(action='fire', port='OnWake'),
                 dict(action='assert', values={'arrival_ui_settle.Running': True})])
        r = Runner(s, source=source(GATE)).run()
        self.assertEqual(r['status'], 'UNSUPPORTED')
        self.assertIsNone(r['filter_gate']['action_profile_sha256'])

    def test_malformed_action_steps_are_errors(self):
        for step in (dict(action='assert_actions'), dict(action='assert_actions', actions={MAP: 'closed'}),
                     dict(action='assert_actions', actions={'nonexistent': 'blocked'}),
                     dict(action='await_action', input=MAP)):
            with self.subTest(step=step):
                self.assertEqual(run([step])['status'], 'ERROR')

    def test_snapshot_load_scenario_resumes_the_hold(self):
        r = run([dict(action='fire', port='OnWake'), dict(action='advance', duration='30s'), dict(action='save', name='mid'),
                 dict(action='advance', duration='2m'), dict(action='assert_actions', actions={MAP: 'allowed'}),
                 dict(action='load', name='mid'), dict(action='assert_actions', actions={MAP: 'blocked'}),
                 dict(action='await_action', input=MAP, timeout='5m', at_least_game='60s')])
        self.assertEqual(r['status'], 'PASS', r['error'])

    def test_cli_run_resolves_the_profile_beside_the_scenario(self):
        tool = Path(__file__).resolve().parents[1] / 'tools/quest_lab_test.py'
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p / 'profile.xml').write_bytes(PROFILE); (p / 'level.xml').write_bytes(level(GATE))
            scenario = dict(schema=1, name='cli gate', source='level.xml', entry='L', action_profile='profile.xml',
                            steps=[dict(action='fire', port='OnLevelSwitched'), dict(action='assert_actions', actions={MAP: 'blocked'}),
                                   dict(action='await_action', input=MAP, timeout='2m', at_least_game='90s')])
            (p / 'scenario.json').write_text(json.dumps(scenario))
            done = subprocess.run([sys.executable, str(tool), 'run', str(p / 'scenario.json'), '--output', str(p / 'out')],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn('native_unknowns', (p / 'out' / 'results.json').read_text())

    def test_html_report_shows_native_unknowns(self):
        from quest_lab.report import write
        r = run([*self.ARRIVE])
        with tempfile.TemporaryDirectory() as temp:
            write([r], temp)
            html = (Path(temp) / 'report.html').read_text(encoding='utf-8')
            self.assertIn('onwake_on_save_load', html)
            self.assertIn('game_time_real_time_scale', html)


class GateAuditTests(unittest.TestCase):
    def test_clean_gate_passes_static_checks_but_lists_every_native_unknown_as_unsupported(self):
        [r] = audit_gates(source(GATE), ActionTable(PROFILE), [MAP, 'use'])
        self.assertEqual(r['status'], 'STATIC_CHECKS_PASSED', r['findings'])
        self.assertEqual(r['findings'], [])
        self.assertTrue(r['apse_actions_blocked'][MAP])
        self.assertTrue(r['apse_actions_blocked']['open_apse_map_controller'])
        self.assertEqual({p['name'].split(': ')[1]: p['engages'] for p in r['probes']},
                         {'OnWake': ['arrival_ui_gate'], 'OnLevelSwitched': ['arrival_ui_gate']})
        self.assertEqual({c['status'] for c in r['native_contracts']}, {'UNSUPPORTED'})
        self.assertEqual([p['active_after_bound'] for p in r['probes']], [[], []])
        self.assertFalse(r['native_runtime_verified'])

    def test_missing_profile_is_partial_not_a_pass(self):
        [r] = audit_gates(source(GATE), None)
        self.assertEqual(r['status'], 'PARTIAL_UNSUPPORTED')

    def test_a_hold_that_never_releases_is_a_leak(self):
        latch = GATE.replace('<Edge From="arrival_ui_settle.Running" To="IsActive"/>', '<Edge From="held.State" To="IsActive"/>') + (
            '<State Name="held" TypeT="bool"><Constant Name="DefaultValue" Value="false"/>'
            '<Edge From="OnWake" To="SetTrue"/><Edge From="OnLevelSwitched" To="SetTrue"/></State>')
        [r] = audit_gates(source(latch), ActionTable(PROFILE))
        self.assertEqual(r['status'], 'FINDINGS')
        self.assertEqual({f['stimulus'] for f in r['findings'] if f['kind'] == 'filter_active_after_bound'},
                         {'OnWake', 'OnLevelSwitched'})
        constant = GATE.replace('<Edge From="arrival_ui_settle.Running" To="IsActive"/>', '<Constant Name="IsActive" Value="true"/>')
        [r] = audit_gates(source(constant), ActionTable(PROFILE))
        self.assertIn('filter_leak', {f['kind'] for f in r['findings']})

    def test_gate_started_by_only_one_entry_event_is_a_finding(self):
        [r] = audit_gates(source(GATE.replace('<Edge From="OnLevelSwitched" To="SetRunning"/>', '')), ActionTable(PROFILE))
        self.assertEqual([(f['kind'], f['stimulus']) for f in r['findings']], [('not_engaged_by_entry_event', 'OnLevelSwitched')])

    def test_unknown_filters_and_uncovered_actions_are_findings(self):
        [r] = audit_gates(source(GATE.replace('no_interaction', 'no_such_filter')), ActionTable(PROFILE))
        self.assertIn('unknown_filter', {f['kind'] for f in r['findings']})
        narrow = GATE.replace('<Constant Name="B" Value="no_interaction"/>', '')
        [r] = audit_gates(source(narrow), ActionTable(PROFILE), [MAP, 'talk', 'nonexistent'])
        kinds = {(f['kind'], f.get('action')) for f in r['findings']}
        self.assertEqual(kinds, {('required_action_not_blocked', 'talk'), ('unknown_action', 'nonexistent')})

    def test_package_audit_and_cli_report_gate_status_and_exit_nonzero_on_findings(self):
        tool = Path(__file__).resolve().parents[1] / 'tools/quest_lab_test.py'
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p / 'profile.xml').write_bytes(PROFILE)
            (p / 'good').mkdir(); (p / 'good' / 'level.xml').write_bytes(level(GATE))
            (p / 'bad').mkdir(); (p / 'bad' / 'level.xml').write_bytes(level(GATE.replace('<Edge From="OnLevelSwitched" To="SetRunning"/>', '')))
            def cli(name, *extra):
                return subprocess.run([sys.executable, str(tool), 'audit', str(p / name), '--profile', str(p / 'profile.xml'),
                                       '--output', str(p / (name + '-out')), *extra], capture_output=True, text=True)
            good = cli('good', '--require-blocked', MAP)
            report = json.loads((p / 'good-out' / 'audit.json').read_text())
            self.assertEqual(report['filter_gates'][0]['status'], 'STATIC_CHECKS_PASSED')
            self.assertIn('Action-filter gates', (p / 'good-out' / 'audit.html').read_text())
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            self.assertEqual(cli('bad').returncode, 1)
            refused = subprocess.run([sys.executable, str(tool), 'audit', str(p / 'good'), '--require-blocked', MAP,
                                      '--output', str(p / 'x')], capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)

    def test_packages_without_filter_inputs_report_no_gates(self):
        s = Source.blobs({'x.xml': level('<State Name="s" TypeT="bool"><Constant Name="DefaultValue" Value="false"/></State>')})
        self.assertEqual(audit(s)['filter_gates'], [])

    def test_filter_input_is_supported_and_level_events_are_exposed(self):
        g = Graph(source(GATE), 'L')
        self.assertFalse([u for u in g.unsupported if 'Unsupported node' in u['reason']])
        self.assertIn('OnWake', g.event_ports)


if __name__ == '__main__': unittest.main()
