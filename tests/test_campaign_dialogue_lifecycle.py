from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_lifecycle import bind, parse, plan
from campaign_quest_bridge import QUEST_ACTIONS
from campaign_quest_graph import emit_project
from test_campaign_quest_graph import model

QUEST = 'arbitrary_quest'


def dialogue(scripts):
    """One decision; each script is the ExitScript of sequence seq_<index>."""
    root = E.Element('Database', Name='brambora')
    host = E.SubElement(E.SubElement(root, 'Skald'), 'FaderDialog', Name='talk')
    E.SubElement(E.SubElement(host, 'Ports'), 'Port', Name='active', Direction='In', Type='bool')
    sequences = E.SubElement(E.SubElement(E.SubElement(host, 'Dialogue'), 'Decision', Name='d1'), 'Sequences')
    for index, script in enumerate(scripts):
        sequence = E.SubElement(sequences, 'Sequence', Name='seq_' + str(index))
        if script is not None: sequence.set('ExitScript', script)
        if index % 2: E.SubElement(E.SubElement(sequence, 'Triggers'), 'Port', Name='other')
        E.SubElement(sequence, 'Elements')
    return E.tostring(root)


def container():
    files, _ = emit_project([model()], 'Example')
    root = E.fromstring(files['Example.xml'])
    E.SubElement(root.find('./Skald/Project/Nodes'), 'talk', Name='talk')
    return E.tostring(root), {QUEST: files['Example/' + QUEST + '.xml']}


def call(function, quest=QUEST):
    return "QuestSystem." + function + "('" + quest + "')"


class LifecycleTests(unittest.TestCase):
    def test_every_mapped_call_becomes_a_port_a_trigger_and_an_edge(self):
        for function, target in QUEST_ACTIONS.items():
            with self.subTest(function=function):
                entry, quests = container()
                blob = dialogue([call(function)])
                found = plan(blob, quests)
                self.assertEqual(found['pending'], [])
                port = 'lifecycle_' + QUEST + '_' + target
                self.assertEqual(found['sites'], [dict(sequence='seq_0', function=function, quest=QUEST,
                                                       input=target, port=port)])
                lowered, wired = bind(blob, entry, found, quests)
                host = E.fromstring(lowered).find('./Skald/FaderDialog')
                declared = host.find("Ports/Port[@Name='" + port + "']")
                self.assertEqual((declared.get('Direction'), declared.get('Type')), ('Out', 'trigger'))
                sequence = host.find(".//Sequence[@Name='seq_0']")
                self.assertIsNone(sequence.get('ExitScript'))
                self.assertEqual([p.get('Name') for p in sequence.findall('Triggers/Port')], [port])
                self.assertEqual([c.tag for c in sequence], ['Triggers', 'Elements'])
                node = E.fromstring(wired).find("./Skald/Project/Nodes/" + QUEST)
                self.assertEqual([(e.get('From'), e.get('To')) for e in node.findall('Edge')],
                                 [('talk.' + port, target)])

    def test_several_calls_in_one_script_and_existing_triggers_are_kept(self):
        entry, quests = container()
        blob = dialogue([None, call('ActivateQuest') + ';\r\n ' + call('StartQuest') + ' '])
        found = plan(blob, quests)
        self.assertEqual([(s['sequence'], s['input']) for s in found['sites']],
                         [('seq_1', 'activate'), ('seq_1', 'start')])
        lowered, wired = bind(blob, entry, found, quests)
        sequence = E.fromstring(lowered).find(".//Sequence[@Name='seq_1']")
        self.assertEqual([p.get('Name') for p in sequence.findall('Triggers/Port')],
                         ['other', 'lifecycle_arbitrary_quest_activate', 'lifecycle_arbitrary_quest_start'])
        self.assertEqual(len(sequence.findall('Triggers')), 1)
        node = E.fromstring(wired).find("./Skald/Project/Nodes/" + QUEST)
        self.assertEqual([e.get('To') for e in node.findall('Edge')], ['activate', 'start'])

    def test_a_script_with_anything_else_stays_pending_and_is_refused(self):
        entry, quests = container()
        for script in (call('StartQuest') + " Utils.GiveItem('x')", "if a then " + call('StartQuest') + " end",
                       call('StartQuest') + " QuestSystem.OpenInventory('" + QUEST + "', 1, 'first')",
                       "QuestSystem.StartQuest(name)", call('StartQuest') + call('StartQuest'),
                       call('CancelQuest'), call('CompleteQuest')):
            with self.subTest(script=script):
                blob = dialogue([script, call('ActivateQuest')])
                found = plan(blob, quests)
                self.assertEqual([p['sequence'] for p in found['pending']], ['seq_0'])
                self.assertEqual([s['sequence'] for s in found['sites']], ['seq_1'])
                with self.assertRaises(ValueError): bind(blob, entry, found, quests)

    def test_scripts_without_a_quest_call_are_not_this_modules_concern(self):
        _, quests = container()
        blob = dialogue(["QuestSystem.OpenInventory('" + QUEST + "', dc['A'].this.id, 'first')",
                         "if QuestSystem.IsQuestStarted('" + QUEST + "') then Utils.Foo() end", "Utils.Foo()"])
        self.assertEqual((plan(blob, quests)['sites'], plan(blob, quests)['pending']), ([], []))
        self.assertIsNone(parse(''))

    def test_unknown_quest_and_missing_instances_are_refused(self):
        entry, quests = container()
        blob = dialogue([call('StartQuest', 'elsewhere')])
        found = plan(blob, quests)
        self.assertEqual(found['pending'][0]['reason'], 'unregistered quest elsewhere')
        with self.assertRaises(ValueError): bind(blob, entry, found, quests)
        blob = dialogue([call('StartQuest')])
        found = plan(blob, quests)
        bare = E.fromstring(entry)
        nodes = bare.find('./Skald/Project/Nodes')
        nodes.remove(nodes.find('talk'))
        with self.assertRaises(ValueError): bind(blob, E.tostring(bare), found, quests)
        portless = E.fromstring(quests[QUEST])
        ports = portless.find('./Skald/Quest/Ports')
        ports.remove(ports.find("Port[@Name='start']"))
        with self.assertRaises(ValueError): bind(blob, entry, plan(blob, [QUEST]), {QUEST: E.tostring(portless)})

    def test_stale_plan_is_refused_and_a_second_run_changes_nothing(self):
        entry, quests = container()
        blob = dialogue([call('StartQuest')])
        found = plan(blob, quests)
        with self.assertRaises(ValueError): bind(dialogue([call('ActivateQuest')]), entry, found, quests)
        lowered, wired = bind(blob, entry, found, quests)
        again = plan(lowered, quests)
        self.assertEqual((again['sites'], again['pending']), ([], []))
        self.assertEqual(bind(lowered, wired, again, quests), (lowered, wired))
        self.assertNotIn(b'QuestSystem.', lowered)


if __name__ == '__main__':
    unittest.main()
