import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_selection import SelectionCompiler
from campaign_dialogue import emit
from test_campaign_dialogue_presentation import model


class DialogueSelectionTests(unittest.TestCase):
    def compiler(self, **changes):
        args = dict(source_types={'0': 'default', '19': 'persuade', '41': 'old_skill'},
                    difficulties=[dict(skill_check_difficulty_id='77', skill_check_difficulty_name='Hard')],
                    reputations=[dict(reputation_change_id='93', name='reward', change='0.1',
                                      can_change_hostility='False', reputation_change_target_id='15')],
                    native_difficulties=[dict(skill_check_difficulty_id='6', skill_check_difficulty_name='Hard')],
                    native_reputations=[dict(reputation_change_id='9', name='reward', change='0.1',
                                             can_change_hostility='false', reputation_change_target_id='15')],
                    native_skills=['persuade', 'new_skill'])
        args.update(changes)
        return SelectionCompiler(**args)

    def test_source_enum_and_registry_ids_are_not_assumed(self):
        self.assertEqual(SelectionCompiler.source_types(
            b'<Types><Enum name="sequenceType"><default value="0"/><persuade value="19"/></Enum></Types>'),
            {'0': 'default', '19': 'persuade'})
        d = model()
        source = d['topics']['1']['sequences'][0]['source']
        source.update(type='19', skill_check_difficulty_id='77', reputation='93')
        blob, _ = emit(d, 'arbitrary_dialogue', [], selection_compiler=self.compiler())
        sequence = ET.fromstring(blob).find('.//Sequence')
        self.assertEqual(sequence.get('SkillCheck'), 'Hard')
        self.assertEqual(sequence.get('SkillCheckType'), 'persuade')
        self.assertEqual(sequence.get('Reputation'), 'reward')

    def test_native_success_fail_branches_are_preserved(self):
        source = model()['topics']['1']['sequences'][0]['source']
        for condition, result in [('skillCheckSuccess', 'Success'), ('skillCheckFail', 'Fail')]:
            attrs, expression = self.compiler().compile(source, condition)
            self.assertEqual(attrs['SkillcheckCondition'], result)
            self.assertEqual(expression, '')
        # Compound expressions cannot be stripped or accidentally made true.
        expression = 'skillCheckSuccess OR Unsupported()'
        self.assertEqual(self.compiler().compile(source, expression)[1], expression)

    def test_renamed_skills_require_explicit_upgrade(self):
        source = model()['topics']['1']['sequences'][0]['source']
        source.update(type='41', skill_check_difficulty_id='77')
        with self.assertRaisesRegex(ValueError, 'sequence type'):
            self.compiler().compile(source, '')
        attrs, _ = self.compiler(skill_adapters={'old_skill': 'new_skill'}).compile(source, '')
        self.assertEqual(attrs['SkillCheckType'], 'new_skill')

    def test_changed_reputation_effect_and_missing_difficulty_are_rejected(self):
        source = model()['topics']['1']['sequences'][0]['source']
        source['reputation'] = '93'
        compiler = self.compiler()
        compiler.native_reputations['reward']['reputation_cap'] = '0.12'
        with self.assertRaisesRegex(ValueError, 'reputation_cap'):
            compiler.compile(source, '')
        source.update(reputation='0', type='19', skill_check_difficulty_id='999')
        with self.assertRaisesRegex(ValueError, 'source dialogue difficulty'):
            compiler.compile(source, '')


    def test_explicit_cap_upgrade_preserves_source_effect_in_separate_table(self):
        native = [dict(reputation_change_id='9', name='reward', change='0.1', reputation_cap='0.12',
                       can_change_hostility='false', reputation_change_target_id='15')]
        compiler = self.compiler(native_reputations=native, preserve_reputation_caps=True)
        source = model()['topics']['1']['sequences'][0]['source']
        source['reputation'] = '93'
        attrs, _ = compiler.compile(source, '')
        self.assertEqual(attrs['Reputation'], 'gm_kcd1_reward')
        root = ET.fromstring(next(iter(compiler.resources().values())))
        row = root.find('.//reputation_change')
        self.assertIsNone(row.get('reputation_cap'))
        self.assertEqual(row.get('change'), '0.1')
        self.assertEqual(row.get('reputation_change_id'), '10')
        self.assertEqual(native[0]['reputation_cap'], '0.12')


if __name__ == '__main__': unittest.main()
