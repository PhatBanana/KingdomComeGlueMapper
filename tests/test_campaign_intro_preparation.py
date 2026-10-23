import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_intro_activity import emit, plan
from campaign_intro_preparation import attach, contract, CONTEXT
from campaign_quest_graph import xml
from test_campaign_combat_runtime import Graph
from test_campaign_intro_initialization import source


def fixture():
    document = source()
    worker = document.find("BehaviorTree[@name='intro']")
    seq = E.fromstring('<Sequence><DisablePerception Perceptor="true" Perceptible="true" ToWhom="craftsman"/>'
                       '<SetTemporarySuperfaction soul="craftsman" superfaction="Friendly"/></Sequence>')
    p = plan(E.tostring(document), 'intro')
    p['parent_quest'] = 'different_parent'
    p['temporary_faction'] = {'preparation': contract(seq, worker, 'craftsman', p)}
    root = E.fromstring('<Database><Skald><Level><Nodes><different_parent Name="parent_instance"/>'
                        '<State Name="example_ended" TypeT="bool"/>'
                        '<Function Name="example_pending" MethodName="math::boolean::Not">'
                        '<Edge From="example_ended.State" To="Value"/></Function>'
                        '<EnableBehavior Name="example_enable" EventSet="resultNotification">'
                        '<Edge From="request.active" To="IsActive"/></EnableBehavior>'
                        '</Nodes></Level></Skald></Database>')
    return p, root, seq, worker


class IntroPreparationTests(unittest.TestCase):
    def graph(self):
        p, root, _, _ = fixture()
        attach(root, 'example', p)
        root.find('Skald/Level').tag = 'Module'
        g = Graph(xml(root))
        effect = g.nodes['example_preparation_guard']
        self.assertEqual(effect.find("Constant[@Name='Context']").get('Value'), CONTEXT)
        self.assertEqual(effect.find('Asset').get('Alias'), 'example_actor')
        return g, effect.find("Edge[@To='IsActive']").get('From')

    def test_guard_precedes_worker_and_releases_on_ack_not_clock_or_success(self):
        g, active = self.graph()
        g.values['request.active'] = False
        self.assertFalse(g.value(active))
        g.values['request.active'] = True
        self.assertTrue(g.value(active))
        for unrelated in ('noon', 'skip_time', 'other_enable.Initialized', 'example_enable.Fail'):
            g.fire(unrelated)
            self.assertTrue(g.value(active))
        g.fire('example_enable.Initialized')
        self.assertFalse(g.value(active))
        g.fire('example_enable.Initialized')
        self.assertFalse(g.value(active))

    def test_cancellation_retirement_and_restored_state_release_protection(self):
        g, active = self.graph()
        g.values['request.active'] = True
        self.assertTrue(g.value(active))
        g.values['request.active'] = False
        self.assertFalse(g.value(active))
        g.values['request.active'] = True
        g.states['example_initialized'] = True  # native persistent State on load
        self.assertFalse(g.value(active))

    def test_invitation_withdrawal_releases_guard_before_initialization(self):
        from campaign_intro_preparation import rebind
        p, root, _, _ = fixture()
        attach(root, 'example', p)
        rebind(root, 'example', 'request.active', 'invitation.intro_active')
        root.find('.//EnableBehavior/Edge').set('From', 'invitation.intro_active')
        attach(root, 'example', p, validate=True)
        root.find('Skald/Level').tag = 'Module'
        g = Graph(xml(root))
        active = g.nodes['example_preparation_guard'].find('Edge').get('From')
        g.values['request.active'] = True
        g.values['invitation.intro_active'] = True
        self.assertTrue(g.value(active))
        # Parent may still be running when its intro request is withdrawn.
        g.values['invitation.intro_active'] = False
        self.assertFalse(g.value(active))
        self.assertFalse(g.states['example_initialized'])

    def test_ack_is_after_full_initializer_and_reissued_without_teleport(self):
        p, _, _, _ = fixture()
        files = emit('example', p)
        tree = E.fromstring(files['AI/example.xml']).find('BehaviorTree')
        init = tree.find('Root/OnInit/Sequence')
        self.assertEqual(init[-1].attrib, {'EventName':"'Initialized'"})
        self.assertEqual(init[-1].tag, 'Callback_empty')
        self.assertFalse(init.find('IfCondition').findall('.//Callback_empty'))
        self.assertEqual(len(tree.findall('.//SetSpatialInfo')), 1)
        self.assertEqual(tree.find('EditorData').get('EventSet'), 'example_initialization')
        events = E.fromstring(files['Libs/Tables/ai/EventSet__example.xml'])
        self.assertEqual({n.get('Name') for n in events.iter('CallbackEventDefinition')},
                         {'Success', 'Fail', 'Initialized'})

    def test_conflicting_graph_and_callback_are_rejected_without_mutation(self):
        p, root, _, _ = fixture()
        self.assertTrue(attach(root, 'example', p))
        self.assertFalse(attach(root, 'example', p))
        attach(root, 'example', p, validate=True)
        root.find('.//SetEntityContext/Constant').set('Value', 'wrong')
        before = E.tostring(root)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            attach(root, 'example', p)
        self.assertEqual(E.tostring(root), before)
        p, root, _, _ = fixture()
        root.find('.//EnableBehavior').set('EventSet', 'unrelated')
        before = E.tostring(root)
        with self.assertRaisesRegex(ValueError, 'callback'):
            attach(root, 'example', p)
        self.assertEqual(E.tostring(root), before)

    def test_requires_source_prepare_before_faction_and_matching_release(self):
        p, _, seq, worker = fixture()
        for target in ('someone_else', ''):
            bad = copy.deepcopy(seq); bad[0].set('ToWhom', target)
            with self.assertRaisesRegex(ValueError, 'ordering'):
                contract(bad, worker, 'craftsman', p)
        bad = copy.deepcopy(seq); operation = bad[0]; bad.remove(operation); bad.append(operation)
        with self.assertRaisesRegex(ValueError, 'ordering'):
            contract(bad, worker, 'craftsman', p)
        bad = copy.deepcopy(worker); bad.find('.//EnablePerception').set('Perceptor', 'false')
        with self.assertRaisesRegex(ValueError, 'ordering'):
            contract(seq, bad, 'craftsman', p)
        seq.remove(seq[0])
        self.assertIsNone(contract(seq, worker, 'craftsman', p))

    def test_receipt_migration_changes_only_verified_callback_contract(self):
        from setup_quest_introductions import migrate_invitation_binding
        from setup_quest_invitation import graph_digest
        p, root, _, _ = fixture()
        before = copy.deepcopy(root.find('.//EnableBehavior'))
        report = dict(graph_nodes={'example_enable': graph_digest(before), 'unrelated': 'untouched'},
                      resources={'source.xml': 'untouched'}, runtime_verified=True)
        attach(root, 'example', p)
        after = root.find('.//EnableBehavior')
        updated, changed = migrate_invitation_binding(report, before, after, 'example', p)
        self.assertTrue(changed)
        self.assertEqual(updated['graph_nodes']['example_enable'], graph_digest(after))
        self.assertEqual(updated['graph_nodes']['unrelated'], 'untouched')
        self.assertEqual(updated['resources'], report['resources'])
        self.assertTrue(report['runtime_verified'])
        self.assertFalse(migrate_invitation_binding(updated, after, after, 'example', p)[1])
        bad = copy.deepcopy(after); bad.find('Edge').set('From', 'unrelated.active')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            migrate_invitation_binding(report, before, bad, 'example', p)
        bad_report = copy.deepcopy(report); bad_report['graph_nodes']['example_enable'] = 'bad'
        with self.assertRaisesRegex(ValueError, 'Unverified'):
            migrate_invitation_binding(bad_report, before, after, 'example', p)


if __name__ == '__main__':
    unittest.main()
