import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.demo import fixtures, generate, model, scenarios
from quest_lab.expressions import assignments, duration, evaluate
from quest_lab.graph import Graph
from quest_lab.report import write
from quest_lab.runner import Runner, run_file
from quest_lab.source import Source
from campaign_quest_graph import emit_project


def empty(extra=''):
    return ('<Database><Skald><Module Name="Test"><Nodes>' + extra +
            '</Nodes></Module></Skald></Database>').encode()


def timed_graph():
    return b'''<Database><Skald><Module Name="Test"><Ports>
      <Port Name="start" Type="trigger" Direction="In"/>
      <Port Name="stop" Type="trigger" Direction="In"/>
      <Port Name="done" Type="trigger" Direction="Out"/></Ports><Nodes>
      <Timer Name="timer"><Constant Name="Duration" Value="1m"/>
        <Constant Name="TimeType" Value="GameTime"/>
        <Edge From="start" To="SetRunning"/><Edge From="stop" To="SetStopped"/></Timer>
      <Output Name="Output"><Edge From="timer.OnFinished" To="done"/></Output>
    </Nodes></Module></Skald></Database>'''


def scenario(steps, **kwargs):
    return dict(schema=1, name='Test', entry='Test', steps=steps, **kwargs)


def run_xml(blob, steps, **kwargs):
    return Runner(scenario(steps, **kwargs), source=Source.blobs({'test.xml':blob})).run()


class QuestLabConvertedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files, cls.adapter = fixtures()

    def test_production_converter_scenarios_pass_with_explicit_engine_boundaries(self):
        for s in scenarios(self.adapter):
            with self.subTest(name=s['name']):
                r = Runner(s, source=Source.blobs(self.files)).run()
                self.assertEqual(r['status'], 'PASS', r['error'])
                self.assertFalse(r['native_runtime_verified'])
                self.assertGreater(len(r['assertions']), 3)
                self.assertTrue(r['graph']['files'])

    def test_missing_scene_release_times_out_instead_of_advancing_training(self):
        s = scenarios(self.adapter)[1]
        s['steps'] = s['steps'][:5] + [dict(action='await',port='output.prepare',timeout='2h')]
        r = Runner(s, source=Source.blobs(self.files)).run()
        self.assertEqual(r['status'], 'TIMEOUT')
        self.assertTrue(r['graph']['states']['at_destination'])
        self.assertIn('output.prepare', r['error'])
        conditions = [e for e in r['timeline'] if e['kind']=='condition' and e['node']=='authorized_preparation']
        self.assertTrue(conditions)
        self.assertFalse(conditions[-1]['result'])

    def test_missing_cleanup_ack_cannot_be_reported_as_lesson_completion(self):
        s = scenarios(self.adapter)[1]
        s['steps'] = s['steps'][:12] + [dict(action='await',port='output.finished',timeout='1h')]
        r = Runner(s, source=Source.blobs(self.files)).run()
        self.assertEqual(r['status'], 'TIMEOUT')
        self.assertTrue(r['graph']['states']['stopping'])

    def test_unknown_native_node_without_contract_is_unsupported(self):
        s = scenarios(self.adapter)[2]; del s['contracts']
        r = Runner(s, source=Source.blobs(self.files)).run()
        self.assertNotEqual(r['status'], 'PASS')
        self.assertIn('training', [u['node'] for u in r['graph']['unsupported']])

    def test_unbound_input_cannot_silently_act_false(self):
        s = scenarios(self.adapter)[1]; del s['inputs']['lesson_authorized']
        r = Runner(s, source=Source.blobs(self.files)).run()
        self.assertEqual(r['status'],'UNSUPPORTED')
        self.assertIn('lesson_authorized',r['error'])

    def test_exclusive_source_branches_cancel_sibling_and_join(self):
        m = model()
        rows = m['tables']['quest_objective']['rows']
        rows[0].update(condition='',autocomplete_timeout_str='')
        for row in rows[:2]:
            row['is_exclusive'] = 'True'
            m['graph']['nodes'][row['objective_id']]['payload'][0]['attributes']['IsExclusive']='1'
        m['tables']['quest_transition']['rows'] = [dict(quest_id='42',from_objective_id=a,to_objective_id=b,enabled='True')
            for a,b in [('1','3'),('1','4'),('3','5'),('4','5'),('5','2')]]
        files,_ = emit_project([m],'Project',startup_quest='example_quest')
        s = dict(schema=1,name='exclusive',entry='Project',steps=[
            dict(action='fire',port='new_game.OnStart'),
            dict(action='fire',port='example_quest.complete_training'),
            dict(action='assert',values={'example_quest.opening_delay_Canceled':True,
                'example_quest.training_Completed':True,'example_quest.return_home_Started':True})])
        r = Runner(s,source=Source.blobs(files)).run()
        self.assertEqual(r['status'],'PASS',r['error'])

    def test_disabled_transition_does_not_start_next_objective(self):
        m = model()
        m['tables']['quest_transition']['rows'][1]['enabled']='False'
        files,_ = emit_project([m],'Project',startup_quest='example_quest')
        s = dict(schema=1,entry='Project',steps=[dict(action='fire',port='new_game.OnStart'),
            dict(action='advance',duration='3m'),
            dict(action='assert',values={'example_quest.training_Started':False})])
        self.assertEqual(Runner(s,source=Source.blobs(files)).run()['status'],'PASS')


class QuestLabClockTests(unittest.TestCase):
    def test_timer_replacement_and_stop_reject_stale_callbacks(self):
        r = run_xml(timed_graph(),[
            dict(action='fire',port='start'),dict(action='advance',duration='30s'),
            dict(action='fire',port='start'),dict(action='advance',duration='30s'),
            dict(action='assert',events={'output.done':0}),dict(action='advance',duration='30s'),
            dict(action='assert',events={'output.done':1}),dict(action='fire',port='start'),
            dict(action='fire',port='stop'),dict(action='advance',duration='2h'),
            dict(action='assert',events={'output.done':1})])
        self.assertEqual(r['status'],'PASS',r['error'])

    def test_timer_snapshot_json_round_trip_retains_deadline(self):
        source=Source.blobs({'test.xml':timed_graph()})
        g=Graph(source,'Test');g.fire('start');g.advance_to(duration('23s'))
        data=json.loads(json.dumps(g.snapshot()))
        restored=Graph(source,'Test');restored.restore(data)
        restored.advance_to(duration('59s'));self.assertEqual(restored.events['output.done'],0)
        restored.advance_to(duration('1m'));self.assertEqual(restored.events['output.done'],1)

    def test_changed_program_rejects_snapshot_before_mutation(self):
        g=Graph(Source.blobs({'x':timed_graph()}),'Test');g.fire('start')
        other=Graph(Source.blobs({'x':timed_graph().replace(b'1m',b'2m')}),'Test')
        with self.assertRaisesRegex(ValueError,'mismatch'):other.restore(g.snapshot())
        self.assertFalse(other.timers)

    def test_normal_and_skip_use_same_explicit_game_time_contract(self):
        traces=[]
        for mode in ('normal','skip'):
            r=run_xml(timed_graph(),[dict(action='fire',port='start'),dict(action='advance',duration='2h',mode=mode),
                                    dict(action='assert',events={'output.done':1})])
            self.assertEqual(r['status'],'PASS')
            traces.append([e for e in r['timeline'] if e['kind']=='timer_finish'])
        self.assertEqual(traces[0],traces[1])
        self.assertEqual(traces[0][0]['time_us'],60000000)

    def test_infinite_zero_delay_loop_is_bounded(self):
        blob=timed_graph().replace(b'<Edge From="stop" To="SetStopped"/>',b'<Edge From="timer.OnFinished" To="SetRunning"/>').replace(b'1m',b'0s')
        r=run_xml(blob,[dict(action='fire',port='start')],budget=100)
        self.assertEqual(r['status'],'TIMEOUT')
        self.assertIn('budget',r['error'])

    def test_duration_is_exact_and_negative_or_unitless_is_rejected(self):
        self.assertEqual(duration('0.1s'),100000)
        for d in ('-1s','1','NaNs','0.0000001s'):
            with self.assertRaises(Unsupported):duration(d)


class QuestLabFailureTests(unittest.TestCase):
    def test_unsupported_unvisited_node_prevents_green_report(self):
        blob=timed_graph().replace(b'<Nodes>',b'<Nodes><ExecuteLua Name="unsafe"/>')
        r=run_xml(blob,[dict(action='assert',events={'output.done':0})])
        self.assertEqual(r['status'],'UNSUPPORTED')
        self.assertEqual(r['graph']['unsupported'][0]['node'],'unsafe')

    def test_unknown_state_setter_and_missing_edge_are_not_ignored(self):
        blob=b'''<Database><Skald><Module Name="Test"><Ports><Port Name="go" Type="trigger" Direction="In"/></Ports><Nodes>
        <State Name="s" TypeT="bool"><Constant Name="DefaultValue" Value="false"/>
        <Edge From="missing.OnTrigger" To="SetMaybe"/></State></Nodes></Module></Skald></Database>'''
        r=run_xml(blob,[dict(action='assert',states={'s':False})])
        self.assertEqual(r['status'],'UNSUPPORTED')
        self.assertEqual(len(r['graph']['unsupported']),2)

    def test_internal_state_cannot_be_overridden_by_scenario_inputs(self):
        blob=empty('<State Name="s" TypeT="bool"><Constant Name="DefaultValue" Value="false"/></State>')
        r=run_xml(blob,[dict(action='set',values={'s.State':True}),dict(action='assert',states={'s':True})])
        self.assertEqual(r['status'],'ERROR')

    def test_assertion_failure_and_unknown_event_are_distinct(self):
        r=run_xml(timed_graph(),[dict(action='assert',events={'output.done':1})])
        self.assertEqual(r['status'],'FAIL')
        r=run_xml(timed_graph(),[dict(action='fire',port='typo')])
        self.assertEqual(r['status'],'ERROR')

    def test_no_assertions_cannot_pass(self):
        r=run_xml(timed_graph(),[dict(action='advance',duration='1s')])
        self.assertEqual(r['status'],'ERROR')

    def test_cyclic_value_dependency_is_reported(self):
        blob=empty('''<Function Name="a" MethodName="math::boolean::Not"><Edge From="b.bool" To="Value"/></Function>
            <Function Name="b" MethodName="math::boolean::Not"><Edge From="a.bool" To="Value"/></Function>''')
        r=run_xml(blob,[dict(action='assert',values={'a.bool':True})])
        self.assertEqual(r['status'],'UNSUPPORTED')
        self.assertIn('Cyclic',r['error'])

    def test_expressions_never_execute_python_or_read_attributes(self):
        for text in ("__import__('os').system('whoami')",'x.__class__', '[x for x in y]', '2**999999999'):
            with self.subTest(text=text),self.assertRaises(Unsupported):evaluate(text,{'x':1})
        self.assertTrue(evaluate("!$ready & ($actor.id == 17)",dict(ready=False,actor={'id':17})))
        self.assertEqual(evaluate("'a!&true,$name'",{}),'a!&true,$name')
        values={'count':3}
        assignments("$count=$count+1,$text='a,b'",values)
        self.assertEqual(values,dict(count=4,text='a,b'))


class QuestLabBehaviorTests(unittest.TestCase):
    def run_behavior(self, body, steps, **config):
        files={'test.xml':empty(), 'AI/test.xml':('<BehaviorTrees><BehaviorTree name="job"><Root><Behavior>'+body+'</Behavior></Root></BehaviorTree></BehaviorTrees>').encode()}
        s=scenario(steps,behaviors=[dict(id='worker',file='AI/test.xml',**config)])
        return Runner(s,source=Source.blobs(files)).run()

    def test_blocked_action_never_succeeds_without_outcome(self):
        body='<Sequence><ExactMove/><Expression expressions="$arrived=true"/></Sequence>'
        start=dict(action='behavior_start',controller='worker',tree='job',task='walk')
        r=self.run_behavior(body,[start,dict(action='advance',duration='2h'),
            dict(action='assert_behavior',controller='worker',tasks={'walk':'external'},variables={'arrived':False})],
            variables={'arrived':False},contracts={'ExactMove':dict(reason='Scenario supplies path outcome')})
        self.assertEqual(r['status'],'PASS',r['error'])

    def test_failure_outcome_stops_sequence(self):
        body='<Sequence><ExactMove/><Expression expressions="$arrived=true"/></Sequence>'
        r=self.run_behavior(body,[dict(action='behavior_start',controller='worker',tree='job',task='walk'),
            dict(action='outcome',controller='worker',task='walk',result='fail'),
            dict(action='assert_behavior',controller='worker',tasks={'walk':'fail'},variables={'arrived':False})],
            variables={'arrived':False},contracts={'ExactMove':dict(reason='Scenario supplies path outcome')})
        self.assertEqual(r['status'],'PASS',r['error'])

    def test_behavior_wait_and_snapshot_resume(self):
        body='<Sequence><Wait duration="2m" timeType="GameTime" doFail="false"/><Expression expressions="$ready=true"/></Sequence>'
        r=self.run_behavior(body,[dict(action='behavior_start',controller='worker',tree='job',task='job'),
            dict(action='advance',duration='1m'),dict(action='save',name='waiting'),
            dict(action='advance',duration='1m'),
            dict(action='assert_behavior',controller='worker',variables={'ready':True},tasks={'job':'success'}),
            dict(action='load',name='waiting'),dict(action='advance',duration='59s',mode='skip'),
            dict(action='assert_behavior',controller='worker',variables={'ready':False}),
            dict(action='advance',duration='1s'),
            dict(action='assert_behavior',controller='worker',variables={'ready':True})],variables={'ready':False})
        self.assertEqual(r['status'],'PASS',r['error'])

    def test_unbound_expression_is_unsupported_not_false(self):
        r=self.run_behavior('<IfCondition condition="$unknown" failOnCondition="false"><Success/></IfCondition>',
            [dict(action='behavior_start',controller='worker',tree='job')])
        self.assertEqual(r['status'],'UNSUPPORTED')

    def test_busy_loop_is_bounded(self):
        files={'test.xml':empty(),'AI/test.xml':b'<BehaviorTrees><BehaviorTree name="spin"><Root><Behavior><While condition="true" doFail="false" propagateChildFail="false"><Success/></While></Behavior></Root></BehaviorTree></BehaviorTrees>'}
        s=scenario([dict(action='behavior_start',controller='worker',tree='spin')],budget=100,
            behaviors=[dict(id='worker',file='AI/test.xml')])
        self.assertEqual(Runner(s,source=Source.blobs(files)).run()['status'],'TIMEOUT')


class QuestLabReportTests(unittest.TestCase):
    def test_source_pak_and_loose_documents_produce_same_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp); (p/'loose').mkdir();(p/'loose'/'quest.xml').write_bytes(timed_graph())
            with zipfile.ZipFile(p/'mod.pak','w') as z:z.writestr('quest.xml',timed_graph())
            a=Graph(Source(p/'loose'),'Test');b=Graph(Source(p/'mod.pak'),'Test')
            self.assertEqual(a.fingerprint,b.fingerprint)

    def test_definition_include_scope_resolves_differing_same_name_modules(self):
        host=b'''<Database><Skald><Project Name="Host"><Definitions><Definition File="chosen/child.xml"/></Definitions>
        <Nodes><Child Name="child"/></Nodes></Project></Skald></Database>'''
        def child(value):
            return ('<Database><Skald><Module Name="Child"><Nodes><State Name="s" TypeT="bool">'
                    '<Constant Name="DefaultValue" Value="'+value+'"/></State></Nodes></Module></Skald></Database>').encode()
        source=Source.blobs({'host.xml':host,'chosen/child.xml':child('true'),'other/child.xml':child('false')})
        self.assertTrue(Graph(source,'Host').value('child.s.State'))
        with self.assertRaises(Unsupported):Graph(source,'Child')
        self.assertFalse(Graph(source,'Child',entry_file='other/child.xml').value('s.State'))

    def test_enum_definition_changes_invalidate_snapshot(self):
        files,_=emit_project([model()],'Project')
        g=Graph(Source.blobs(files),'example_quest')
        altered=dict(files)
        altered['Project.xml']=altered['Project.xml'].replace(b'Name="Canceled"',b'Name="Abandoned"')
        other=Graph(Source.blobs(altered),'example_quest')
        self.assertNotEqual(g.fingerprint,other.fingerprint)

    def test_bad_json_and_missing_scenario_produce_error_results(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bad.json'
            self.assertEqual(run_file(path)['status'],'ERROR')
            path.write_text('{')
            self.assertEqual(run_file(path)['status'],'ERROR')

    def test_engine_activation_changes_are_observed_not_auto_completed(self):
        files,adapter=fixtures()
        r=Runner(scenarios(adapter)[1],source=Source.blobs(files)).run()
        self.assertEqual(r['status'],'PASS',r['error'])
        changes=[e['values']['IsActive'] for e in r['timeline'] if e['kind']=='external_inputs']
        self.assertEqual(changes,[False,True,False])

    def test_reports_escape_source_text_and_do_not_hide_unsupported_in_junit(self):
        r=run_xml(timed_graph(),[dict(action='assert',events={'output.done':0})])
        r['name']='<script>alert(1)</script>';r['status']='UNSUPPORTED'
        with tempfile.TemporaryDirectory() as temp:
            write([r],temp)
            html=(Path(temp)/'report.html').read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
            self.assertNotIn('<script>alert(1)</script>',html)
            root=E.parse(Path(temp)/'junit.xml').getroot()
            self.assertEqual(root.get('errors'),'1')
            self.assertIsNotNone(root.find('testcase/error'))

    def test_cli_demo_run_and_failure_exit_code(self):
        tool=Path(__file__).resolve().parents[1]/'tools/quest_lab_test.py'
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp); paths=generate(p/'demo')
            completed=subprocess.run([sys.executable,str(tool),'run',*map(str,paths),'--output',str(p/'report')],capture_output=True,text=True)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            self.assertTrue((p/'report'/'report.html').is_file())
            s=json.loads(paths[0].read_text());s['steps']=[dict(action='assert',values={'example_quest.completed':True})]
            paths[0].write_text(json.dumps(s))
            completed=subprocess.run([sys.executable,str(tool),'run',str(paths[0]),'--output',str(p/'failure')],capture_output=True,text=True)
            self.assertEqual(completed.returncode,1,completed.stdout+completed.stderr)
            self.assertEqual(json.loads((p/'failure'/'results.json').read_text())['results'][0]['status'],'FAIL')


if __name__=='__main__': unittest.main()
