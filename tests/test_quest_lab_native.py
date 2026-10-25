import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.graph import Graph
from quest_lab.runner import Runner
from quest_lab.source import Source


XML = b'''<Database><Skald><Module Name="M"><Ports>
<Port Name="a" Direction="In" Type="trigger"/><Port Name="b" Direction="In" Type="trigger"/>
<Port Name="door" Direction="In" Type="string"/><Port Name="done" Direction="Out" Type="trigger"/></Ports>
<Nodes><Function Name="open" DeclaringType="wh::entitymodule" MethodName="wh::entitymodule::OpenDoor">
<Edge From="a" To="Exec"/><Edge From="b" To="Exec"/><Edge From="door" To="Door"/></Function>
<Output Name="out"><Edge From="open.OnExec" To="done"/></Output></Nodes></Module></Skald></Database>'''


def source(blob=XML): return Source.blobs({'x.xml':blob})


def contract():
    return {'open':dict(reason='Explicit test outcome; door physics is not simulated',
        native=dict(kind='Function', declaring_type='wh::entitymodule', method='wh::entitymodule::OpenDoor'),
        inputs={'Exec':'trigger','Door':'value'}, outputs={'OnExec':'trigger'})}


class NativeCallTests(unittest.TestCase):
    def test_fanin_captures_independent_requests_without_completing_them(self):
        g=Graph(source(),'M',contracts=contract()); self.assertEqual(g.unsupported,[])
        # Arguments are not queried until execution, unlike persistent effects.
        g.observe_contracts()
        g.set_inputs({'door':'first'});g.fire('a')
        g.set_inputs({'door':'second'});g.fire('b')
        self.assertEqual([c['arguments'] for c in g.native.pending],[{'Door':'first'},{'Door':'second'}])
        self.assertEqual([c['id'] for c in g.native.pending],[1,2])
        self.assertEqual(g.events['output.done'],0)
        g.native.resolve(2,'open','returned',events=['OnExec'])
        self.assertEqual(g.events['output.done'],1)
        self.assertEqual([c['id'] for c in g.native.pending],[1])
        g.native.resolve(1,'open','aborted')
        self.assertEqual(g.events['output.done'],1)

    def test_pending_result_prevents_a_false_pass_and_explicit_response_unblocks(self):
        s=dict(schema=1,entry='M',contracts=contract(),inputs={'door':'fixture'},steps=[
            dict(action='fire',port='a'),dict(action='assert_native',count=1),
            dict(action='assert',events={'output.done':0})])
        self.assertEqual(Runner(s,source=source()).run()['status'],'UNSUPPORTED')
        s['steps'] += [dict(action='native_result',id=1,node='open',result='returned',events=['OnExec']),
                       dict(action='assert',events={'output.done':1}),dict(action='assert_native',count=0)]
        r=Runner(s,source=source()).run()
        self.assertEqual(r['status'],'PASS',r['error']);self.assertFalse(r['native_runtime_verified'])

    def test_uncontracted_call_remains_unsupported_but_fanin_does_not_block_loading(self):
        g=Graph(source(),'M');self.assertTrue(g.unsupported);g.set_inputs({'door':'fixture'})
        with self.assertRaisesRegex(Unsupported,'explicit interface'):g.fire('a')

    def test_results_cannot_bypass_request_or_be_reused(self):
        g=Graph(source(),'M',contracts=contract());g.set_inputs({'door':'fixture'})
        with self.assertRaisesRegex(ValueError,'Unknown'):g.native.resolve(1,'open','returned',events=['OnExec'])
        with self.assertRaisesRegex(ValueError,'native_result'):g.fire('open.OnExec')
        g.fire('a')
        for identity,node,result,events in [(True,'open','returned',[]),(1,'wrong','returned',[]),
                (1,'open','returned',['unknown']),(1,'open','returned',['OnExec','OnExec']),
                (1,'open','aborted',['OnExec']),(1,'open','success',[])]:
            before=g.native.snapshot()
            with self.assertRaises(ValueError):g.native.resolve(identity,node,result,events=events)
            self.assertEqual(before,g.native.snapshot())
        g.native.resolve(1,'open','returned',events=['OnExec'])
        with self.assertRaises(ValueError):g.native.resolve(1,'open','returned',events=['OnExec'])
        self.assertEqual(g.events['output.done'],1)

    def test_typed_return_values_are_atomic_and_cannot_be_injected_early(self):
        c=contract();c['open']['outputs'].update(ok='bool',count='int')
        g=Graph(source(),'M',contracts=c);g.set_inputs({'door':'fixture'})
        with self.assertRaisesRegex(ValueError,'native_result'):g.set_inputs({'open.ok':True})
        g.fire('a')
        for values in ({'ok':True},{'ok':1,'count':2},{'ok':True,'count':False}):
            with self.assertRaises(ValueError):g.native.resolve(1,'open','returned',values, ['OnExec'])
            self.assertEqual(len(g.native.pending),1);self.assertNotIn('open.ok',g.external_values)
        g.native.resolve(1,'open','returned',{'ok':False,'count':2},['OnExec'])
        self.assertFalse(g.value('open.ok'));self.assertEqual(g.value('open.count'),2)

    def test_assets_require_explicit_identity_binding(self):
        blob=XML.replace(b'<Edge From="door" To="Door"/>',b'<Asset Name="Door" Alias="rental_door"/>')
        g=Graph(source(blob),'M',contracts=contract())
        with self.assertRaisesRegex(Unsupported,'Unbound asset'):g.fire('a')
        g=Graph(source(blob),'M',contracts=contract(),assets={'rental_door':'door-42'})
        g.fire('a');self.assertEqual(g.native.pending[0]['arguments'],{'Door':'door-42'})

    def test_save_replay_and_changed_contract_identity(self):
        g=Graph(source(),'M',contracts=contract());g.set_inputs({'door':'fixture'});g.fire('a')
        saved=json.loads(json.dumps(g.snapshot()))
        g.native.resolve(1,'open','returned',events=['OnExec']);g.restore(saved)
        self.assertEqual(len(g.native.pending),1)
        g.native.resolve(1,'open','returned',events=['OnExec']);self.assertEqual(g.events['output.done'],2)
        c=contract();c['open']['reason']='different contract'
        other=Graph(source(),'M',contracts=c)
        with self.assertRaisesRegex(ValueError,'mismatch'):other.restore(saved)

    def test_contract_identity_and_builtin_logic_are_protected(self):
        c=contract();c['open']['native']['method']='wh::entitymodule::CloseDoor'
        with self.assertRaisesRegex(ValueError,'signature mismatch'):Graph(source(),'M',contracts=c)
        c=contract();c['open']['values']={'ok':True}
        with self.assertRaisesRegex(ValueError,'after a request'):Graph(source(),'M',contracts=c)
        blob=XML.replace(b'wh::entitymodule::OpenDoor',b'math::boolean::And')
        with self.assertRaisesRegex(ValueError,'Cannot replace interpreted'):Graph(source(blob),'M',contracts=contract())


if __name__=='__main__':unittest.main()
