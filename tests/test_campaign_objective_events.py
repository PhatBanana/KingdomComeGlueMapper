import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import copy
import unittest
import xml.etree.ElementTree as ET
from campaign_objective_events import bind


def node(op, children=(), **attrs):
    return dict(op=op, attributes=attrs, children=list(children))


def fixture():
    action = node('SetQuestObjective', quest='', objective='parent', function='CompleteObjective')
    guard = node('QuestObjectiveCondition', [node('Then', [action])], quest='', objective='parent', function='IsObjectiveStarted')
    gate = node('IfCondition', [node('Sequence', [guard])], condition="($event.ObjectiveName == 'child') & ($event.State == $enum:ObjectiveState.Completed)")
    root = node('Root', [node('ProcessMessage', [node('Switch', [gate])], inbox='QuestMailbox', variable='event', condition='')])
    model = dict(quest='test', behavior_entry='test', behavior_documents={'test':{'trees':{'onUpdate':{'root':root}}}}, tables={'quest_objective':{'rows':[dict(objective_name='child',objective_id='1'),dict(objective_name='parent',objective_id='2')]}})
    nodes = ET.fromstring('<Nodes><State Name="objective_1"/><State Name="objective_2"/></Nodes>')
    return model, nodes, gate


class ObjectiveEvents(unittest.TestCase):
    def test_source_event_completes_parent_once(self):
        model, nodes, _ = fixture()
        self.assertEqual(bind(nodes,model),[dict(objective='child',event='Completed',actions=1)])
        text = ET.tostring(nodes).decode()
        self.assertIn('objective_1.OnCompleted',text)
        self.assertIn('objective_2.Started',text)
        self.assertIn('SetCompleted',text)
        self.assertEqual(bind(nodes,model),[])

    def test_unsupported_action_rejects_entire_branch(self):
        model,nodes,gate = fixture()
        gate['children'][0]['children'].append(node('ExecuteLua',code='anything'))
        self.assertEqual(bind(nodes,model),[])
        self.assertEqual(len(nodes),2)

    def test_context_guard_is_not_discarded(self):
        model,nodes,gate = fixture()
        root=model['behavior_documents']['test']['trees']['onUpdate']['root']
        root['children']=[node('IfCondition',root['children'],condition='some_other_condition')]
        self.assertEqual(bind(nodes,model),[])

    def test_external_quest_is_not_changed(self):
        model,nodes,gate=fixture()
        gate['children'][0]['children'][0]['attributes']['quest']='other'
        self.assertEqual(bind(nodes,model),[])
