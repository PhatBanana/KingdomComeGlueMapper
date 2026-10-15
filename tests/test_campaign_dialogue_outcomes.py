import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_outcomes import outcomes, lower, refresh
from campaign_dialogue import emit
from test_campaign_dialogue_presentation import model


class OutcomeTests(unittest.TestCase):
    def test_refresh_requires_matching_source_and_preserves_existing_media(self):
        source = model()
        source['functions'] = {'skillCheckSuccess': "var('success') >= 0"}
        source['topics']['1']['sequences'][0]['entry']['entry_condition'] = 'skillCheckSuccess OR 0'
        blob = b'''<Database><Skald><FaderDialog><Ports><Port Name="enabled"/></Ports><Dialogue>
          <Decision Name="topic_1"><Sequences><Sequence Name="seq_10"
          EntryCondition="Port('enabled') AND ((var('success') &gt;= 0) OR 0)">
          <Responses><Response StringName="recorded" Facial="face"/></Responses>
          </Sequence></Sequences></Decision></Dialogue></FaderDialog></Skald></Database>'''
        result, aliases = refresh(blob, source, [])
        self.assertEqual(len(aliases), 1)
        rows = ET.fromstring(result).findall('.//Response')
        self.assertEqual([r.attrib for r in rows], [dict(StringName='recorded', Facial='face')] * 2)
        for sequence in ET.fromstring(result).iter('Sequence'):
            self.assertTrue(sequence.get('EntryCondition').startswith("Port('enabled')"))
        with self.assertRaisesRegex(ValueError, 'differs from source'):
            refresh(blob.replace(b'OR 0)', b'OR 1)'), source, [])

    def test_full_emitter_uses_native_result_and_history_for_both_copies(self):
        from test_campaign_dialogue_selection import DialogueSelectionTests
        source = model()
        source['functions'] = {'skillCheckSuccess': "var('success') >= 0"}
        row = source['topics']['1']['sequences'][0]
        row['entry']['entry_condition'] = 'skillCheckSuccess OR 0'
        row['source']['timeout'] = '-1'
        blob, report = emit(source, 'arbitrary', [],
                            selection_compiler=DialogueSelectionTests().compiler())
        self.assertNotIn(b"var('success')", blob)
        rows = ET.fromstring(blob).findall('.//Sequence')
        self.assertEqual([r.get('SkillcheckCondition') for r in rows], ['Success', 'Fail'])
        self.assertEqual([r.get('Visibility') for r in rows], ['Internal', 'Internal'])
        self.assertEqual(report['skill_outcome_aliases'], {'seq_10': 'seq_10_skill_fail'})

    def test_compound_truth_tables_preserve_or_and_negation(self):
        for expression in ('skillCheckSuccess OR beaten',
                           'skillCheckFail AND !beaten',
                           '!(skillCheckFail AND beaten)'):
            variants = outcomes(expression, {})
            for success in (False, True):
                for beaten in (False, True):
                    def evaluate(s):
                        return bool(eval(s.replace('AND', 'and').replace('OR', 'or')
                                         .replace('!', 'not '), {}, dict(
                                             skillCheckSuccess=success,
                                             skillCheckFail=not success, beaten=beaten)))
                    self.assertEqual(evaluate(expression), evaluate(
                        variants['Success' if success else 'Fail']))

    def test_helpers_expand_without_expanding_engine_result_or_quoted_names(self):
        result = outcomes('helper OR IsSomething(\'skillCheckFail\')', dict(
            helper='skillCheckSuccess AND ready', skillCheckSuccess="var('success') >= 0"))
        self.assertEqual(result['Fail'], "(0 AND ready) OR IsSomething('skillCheckFail')")
        self.assertIsNone(outcomes("IsSomething('skillCheckFail')", {}))
        self.assertIsNone(outcomes('skillCheckSuccess', {}))

    def test_split_preserves_payload_and_combines_history(self):
        root = ET.fromstring('''<Dialogue><Decision><Sequences>
          <Sequence Name="seq_7" EndType="EndDialogue" Reputation="penalty">
            <Responses><Response StringName="voice_7" Role="npc"/></Responses>
            <Action Name="objective_started"/>
          </Sequence><Sequence Name="seq_8" EntryCondition="!SequenceUsed('seq_7')"/>
        </Sequences></Decision></Dialogue>''')
        lower(root, {'seq_7': {'Success': '1 OR ready', 'Fail': '0 OR ready'}})
        a, b, c = list(root.find('.//Sequences'))
        self.assertEqual(a.get('SkillcheckCondition'), 'Success')
        self.assertEqual(b.get('SkillcheckCondition'), 'Fail')
        self.assertEqual([ET.tostring(n) for n in a], [ET.tostring(n) for n in b])
        self.assertEqual(b.get('Reputation'), 'penalty')
        self.assertEqual(c.get('EntryCondition'), "!(SequenceUsed('seq_7') OR SequenceUsed('seq_7_skill_fail'))")

    def test_interactive_branch_is_rejected(self):
        root = ET.fromstring('<Dialogue><Sequences><Sequence Name="seq_7"><UiPrompt/></Sequence></Sequences></Dialogue>')
        with self.assertRaisesRegex(ValueError, 'automatic response'):
            lower(root, {'seq_7': {'Success': '1', 'Fail': '0'}})

    def test_nested_continuation_has_one_identity_shared_by_results(self):
        root = ET.fromstring('''<Dialogue><Sequences><Sequence Name="seq_7" EndType="Decision">
          <Decision Name="next"><Sequences><Sequence Name="seq_9"/></Sequences></Decision>
        </Sequence></Sequences></Dialogue>''')
        lower(root, {'seq_7': {'Success': '1', 'Fail': '0'}})
        self.assertEqual(len(root.findall('.//Decision')), 1)
        alternate = root.find(".//Sequence[@Name='seq_7_skill_fail']")
        self.assertEqual(alternate.get('EndType'), 'GoTo')
        self.assertEqual(alternate.get('GoToDecision'), 'next')
        self.assertEqual(len(root.findall(".//Sequence[@Name='seq_9']")), 1)


if __name__ == '__main__':
    unittest.main()
