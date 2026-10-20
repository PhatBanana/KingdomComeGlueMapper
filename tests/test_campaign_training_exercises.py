import copy
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_training_exercises import resolve, bind, compile_exercises, ExerciseConversionError
from campaign_quest_graph import objective_identifier
from test_campaign_behavior import source, catalog


def fixture():
    model = source('<Root><Behavior><Wait duration="1s" timeType="GameTime" doFail="false" variation="" skipInLOD="false"/></Behavior></Root>')
    doc = next(iter(model['behavior_documents']))
    trees = model['behavior_documents'][doc]['trees']
    program = trees.pop('onUpdate')
    trees.update(alpha=copy.deepcopy(program), beta=copy.deepcopy(program))
    model['tables']['quest_objective']['rows'] = [dict(quest_id=model['quest_id'], objective_id=str(i), objective_name=n)
        for i,n in enumerate(['03_first','01_second','unused','finish'])]
    model['tables']['quest_transition']['rows'] = [dict(quest_id=model['quest_id'],from_objective_id=a,to_objective_id=b,enabled=e)
        for a,b,e in [('0','1','True'),('0','2','False'),('1','3','True')]]
    bindings = {n:dict(document=doc,tree=t) for n,t in [('03_first','alpha'),('01_second','beta')]}
    return model, bindings


class ExerciseTests(unittest.TestCase):
    def test_terminal_exercise_without_outgoing_edge(self):
        model,bindings=fixture()
        model['tables']['quest_transition']['rows'].pop()
        seq=resolve(model,'03_first','01_second',bindings,include_exit=True)
        self.assertEqual(len(seq['stages']),2)
        files,bridge,report=compile_exercises(model,seq,'Imported',catalog())
        self.assertTrue(files)
        self.assertFalse(report['runtime_validated'])

    def test_source_edges_not_number_order_and_no_disabled_exercises(self):
        model, bindings = fixture(); before=copy.deepcopy(model)
        result=resolve(model,'03_first','finish',bindings)
        self.assertEqual([s['objective'] for s in result['stages']],['03_first','01_second'])
        self.assertEqual(model,before)
        self.assertEqual(result['stages'][0]['objective_port'],objective_identifier('03_first'))
        self.assertEqual(result['stages'][0]['tree'],'alpha')

    def test_branches_cycles_missing_programs_and_dead_ends_rejected(self):
        for change in ('branch','cycle','missing','dead'):
            model,bindings=fixture(); transitions=model['tables']['quest_transition']['rows']
            if change=='branch': transitions[1]['enabled']='True'
            if change=='cycle': transitions[-1]['to_objective_id']='0'
            if change=='missing': bindings.pop('01_second')
            if change=='dead': transitions[-1]['enabled']='False'
            with self.subTest(change=change),self.assertRaises(ValueError):
                resolve(model,'03_first','finish',bindings)

    def test_unrelated_virtual_endpoints_do_not_block_lesson(self):
        model,bindings=fixture()
        model['tables']['quest_transition']['rows'].append(dict(
            quest_id=model['quest_id'],from_objective_id='virtual_start',
            to_objective_id='virtual_end',enabled='True'))
        self.assertEqual(len(resolve(model,'03_first','finish',bindings)['stages']),2)

    def test_stale_program_or_transition_plan_rejected(self):
        for change in ('program','transition'):
            model,bindings=fixture(); seq=resolve(model,'03_first','finish',bindings)
            if change=='program':
                doc=next(iter(model['behavior_documents']))
                model['behavior_documents'][doc]['trees']['alpha']['variables']=[]
            else:
                model['tables']['quest_transition']['rows'][0]['enabled']='False'
            with self.subTest(change=change),self.assertRaises(ValueError):
                compile_exercises(model,seq,'Imported',catalog())

    def test_worker_binding_uses_encoded_objectives_and_no_native_phase(self):
        model,bindings=fixture(); seq=resolve(model,'03_first','finish',bindings)
        root=E.Element('Database'); q=E.SubElement(E.SubElement(root,'Skald'),'Quest'); ports=E.SubElement(q,'Ports')
        nodes=E.Element('Nodes'); quest=E.SubElement(nodes,'Quest',Name='quest')
        workers={}
        for i,stage in enumerate(seq['stages']):
            E.SubElement(ports,'Port',Name=stage['objective_port']+'_Started',Direction='Out',Type='bool')
            workers[stage['objective']]=E.SubElement(nodes,'EnableBehavior',Name='worker'+str(i))
        bind(nodes,quest,E.tostring(root),seq,workers,'host.active')
        self.assertEqual(len(nodes.findall('.//Edge[@To="IsActive"]')),2)
        self.assertFalse(nodes.findall('CombatTutorialNode'))
        self.assertFalse(quest.findall('Edge'))  # No fake objective completion.
        before=E.tostring(nodes)
        with self.assertRaises(ValueError): bind(nodes,quest,E.tostring(root),seq,workers,'host.active')
        self.assertEqual(E.tostring(nodes),before)

    def test_unsupported_exercise_withholds_whole_lesson(self):
        model,bindings=fixture()
        doc=next(iter(model['behavior_documents']))
        model['behavior_documents'][doc]['trees']['beta']['root']['children'][0]['children'][0]['op']='UnknownExerciseListener'
        seq=resolve(model,'03_first','finish',bindings)
        with self.assertRaises(ExerciseConversionError) as caught:
            compile_exercises(model,seq,'Imported',catalog())
        self.assertTrue(any('UnknownExerciseListener' in e['reason'] for r in caught.exception.report['trees'] for e in r['unresolved']))


if __name__ == '__main__': unittest.main()
