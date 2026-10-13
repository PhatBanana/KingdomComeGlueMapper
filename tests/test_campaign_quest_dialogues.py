import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_dialogues import discover


class QuestDialogueDiscoveryTests(unittest.TestCase):
    def test_unnamed_root_is_found_through_nested_callback_and_cycles_terminate(self):
        tables = dict(topic=[dict(topic_id=i, label='') for i in ['1','2','3']],
                      sequence=[dict(sequence_id='10', next='2'), dict(sequence_id='20', next='1'),
                                dict(sequence_id='30', next='0')],
                      topic2sequence=[dict(topic_id=i, sequence_id=i+'0', entry_condition='') for i in ['1','2','3']],
                      sequence2quest_objective=[dict(quest_id='42', sequence_id='20', objective_id='9')],
                      v_branch=[dict(start_topic='1'),dict(start_topic='3')], topictorole=[])
        report = discover(tables, '42', 'arbitrary')
        self.assertEqual([b['topic']['topic_id'] for b in report['branches']], ['1'])
        self.assertEqual(report['references'][0]['topic_id'], '2')
        tables['sequence2quest_objective'] = []
        tables['topic2sequence'][2]['entry_condition'] = "IsQuestStarted('arbitrary')"
        self.assertEqual([b['topic']['topic_id'] for b in discover(tables,'42','arbitrary')['branches']], ['3'])
        self.assertEqual(discover(tables,'42','arbitrary_extra')['branches'], [])


if __name__ == '__main__': unittest.main()
