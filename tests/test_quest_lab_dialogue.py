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


DIALOGUE = b'''<Database><Skald><ForcedDialog Name="Talk"><Ports>
<Port Name="active" Direction="In" Type="bool"/><Port Name="ready" Direction="In" Type="bool"/>
<Port Name="accepted" Direction="Out" Type="trigger"/></Ports>
<Dialogue TechnicalStatus="Enabled"><Decision Name="root"><Sequences>
<Sequence Name="accept" EndType="Decision" EntryCondition="Port('active') AND Port('ready') AND !SequenceUsed('accept')">
<Triggers><Port Name="accepted"/></Triggers><Elements><Response Role="HENRY"><Text Text="Yes"/></Response></Elements>
<Decision Name="follow"><Sequences><Sequence Name="back" EndType="GoTo" GoToDecision="root"/></Sequences></Decision>
</Sequence><Sequence Name="leave" EndType="EndDialogue" EntryCondition="Port('active')"/>
</Sequences></Decision></Dialogue></ForcedDialog></Skald></Database>'''

HOST = b'''<Database><Skald><Module Name="Host"><Definitions><Definition File="dialogue.xml"/></Definitions><Ports>
<Port Name="one" Direction="In" Type="trigger"/><Port Name="two" Direction="In" Type="trigger"/>
<Port Name="ready" Direction="In" Type="bool"/></Ports><Nodes>
<State Name="done" TypeT="bool"><Constant Name="DefaultValue" Value="false"/><Edge From="talk.accepted" To="SetTrue"/></State>
<State Name="closed" TypeT="bool"><Constant Name="DefaultValue" Value="false"/><Edge From="talk.AfterPlay" To="SetTrue"/></State>
<Talk Name="talk"><Constant Name="active" Value="true"/><Edge From="ready" To="ready"/>
<Edge From="one" To="EnqueueDialogue"/><Edge From="two" To="EnqueueDialogue"/></Talk>
</Nodes></Module></Skald></Database>'''


def source(dialogue=DIALOGUE):
    return Source.blobs({'dialogue.xml': dialogue, 'host.xml': HOST})


class DialogueTests(unittest.TestCase):
    def test_requests_do_not_implicitly_start_or_complete_a_scene(self):
        g = Graph(source(), 'Host')
        self.assertEqual(g.unsupported, [])
        g.set_inputs({'ready': True}); g.fire('one'); g.fire('two')
        self.assertEqual(g.dialogues['talk'].state['requests'], ['EnqueueDialogue'] * 2)
        self.assertFalse(g.dialogues['talk'].state['active'])
        self.assertFalse(g.states['done']); self.assertFalse(g.states['closed'])
        g.dialogues['talk'].start(request=True)
        self.assertEqual(g.events['talk.BeforePlay'], 1)
        self.assertEqual(g.dialogues['talk'].state['requests'], ['EnqueueDialogue'])

    def test_conditions_branch_return_history_save_and_actual_graph_effects(self):
        scenario = dict(schema=1, entry='Host', inputs={'ready':False}, steps=[
            dict(action='dialogue_start', dialogue='talk'),
            dict(action='assert_dialogue', dialogue='talk', choices=['leave']),
            dict(action='set', values={'ready':True}),
            dict(action='assert_dialogue', dialogue='talk', choices=['accept','leave']),
            dict(action='save', name='before'),
            dict(action='dialogue_choose', dialogue='talk', sequence='accept'),
            dict(action='assert', states={'done':True, 'closed':False}),
            dict(action='assert_dialogue', dialogue='talk', choices=['back']),
            dict(action='dialogue_choose', dialogue='talk', sequence='back'),
            dict(action='assert_dialogue', dialogue='talk', choices=['leave']),
            dict(action='dialogue_choose', dialogue='talk', sequence='leave'),
            dict(action='assert_dialogue', dialogue='talk', choices=[], state={'active':True,'closing':True}),
            dict(action='dialogue_end', dialogue='talk'),
            dict(action='assert', states={'closed':True}),
            dict(action='load', name='before'),
            dict(action='assert', states={'done':False,'closed':False}),
            dict(action='assert_dialogue', dialogue='talk', choices=['accept','leave']),
            dict(action='dialogue_end', dialogue='talk'),
            dict(action='assert', states={'done':False,'closed':True})])
        r = Runner(scenario, source=source()).run()
        self.assertEqual(r['status'], 'PASS', r['error'])
        self.assertFalse(r['native_runtime_verified'])

    def test_unavailable_duplicate_selection_and_unrequested_start_are_rejected(self):
        g = Graph(source(), 'Host'); g.set_inputs({'ready':False}); d = g.dialogues['talk']
        with self.assertRaisesRegex(ValueError, 'pending'): d.start(True)
        d.start()
        with self.assertRaisesRegex(ValueError, 'not available'): d.choose('accept')
        self.assertFalse(g.states['done'])
        with self.assertRaisesRegex(ValueError, 'already active'): d.start()
        g.set_inputs({'ready':True}); d.choose('accept'); d.choose('back')
        with self.assertRaisesRegex(ValueError, 'not available'): d.choose('accept')

    def test_json_snapshot_preserves_pending_request_active_branch_and_sequence_use(self):
        g = Graph(source(), 'Host'); g.set_inputs({'ready':True}); g.fire('one')
        d = g.dialogues['talk']; d.start(); d.choose('accept')
        snapshot = json.loads(json.dumps(g.snapshot()))
        d.choose('back'); d.end(); g.restore(snapshot)
        self.assertEqual(d.choices(), ['back'])
        self.assertEqual(d.state['used'], ['accept'])
        self.assertEqual(d.state['requests'], ['EnqueueDialogue'])

    def test_root_dialogue_ports_and_afterplay_cannot_be_forged(self):
        g = Graph(source(), 'Talk'); g.set_inputs({'active':True,'ready':True})
        self.assertEqual(g.unsupported, [])
        with self.assertRaises(ValueError): g.fire('output.accepted')
        g.dialogues['Talk'].start(); g.dialogues['Talk'].choose('accept')
        self.assertEqual(g.events['output.accepted'], 1)
        with self.assertRaisesRegex(ValueError, 'replace dialogue'):
            Graph(source(), 'Host', contracts={'talk':{'reason':'bypass','outputs':{}}})

    def test_unknown_condition_even_in_short_circuited_branch_is_not_silently_true(self):
        for condition in ("true OR NativeCall()", "Port('missing')", "SequenceUsed('missing')"):
            blob = DIALOGUE.replace(b"Port('active') AND Port('ready') AND !SequenceUsed('accept')", condition.encode())
            g = Graph(source(blob), 'Host'); g.set_inputs({'ready':True}); d = g.dialogues['talk']; d.start()
            self.assertTrue(g.unsupported)
            with self.assertRaises(Unsupported): d.choices()
            self.assertFalse(g.states['done'])

    def test_unmodeled_scripts_or_selection_attributes_prevent_effects(self):
        for extra in ('ExitScript="NativeCall()"', 'Cooldown="10"', 'SkillCheck="Strength"'):
            blob = DIALOGUE.replace(b'Name="accept"', ('Name="accept" ' + extra).encode())
            g = Graph(source(blob), 'Host'); g.set_inputs({'ready':True}); d = g.dialogues['talk']; d.start()
            with self.assertRaises(Unsupported): d.choose('accept')
            self.assertFalse(g.states['done']); self.assertEqual(d.state['used'], [])


if __name__ == '__main__': unittest.main()
