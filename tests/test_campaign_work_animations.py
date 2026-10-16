from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

from test_campaign_behavior import source, catalog
from campaign_behavior import convert_behaviors
from campaign_work_animations import DATABASES, fragment_catalog


def native_catalog():
    result = catalog()
    result['nodes']['AnimationAction'] = dict(attributes=['fragment', 'tags', 'context',
        'keepContext', 'eventReferenceObject', 'alignObject', 'slaveObject', 'resourceOverride'], children=[])
    result['work_animations'] = dict(common_human_fragments=['CommonWork'])
    return result


class WorkAnimationTests(unittest.TestCase):
    def gender_catalog(self):
        native = native_catalog()
        native['nodes']['HasGenderCheck'] = dict(attributes=['Gender','SoulWUID','FailSubtMissing','saveVersion'], children=['Then','Else'])
        native['work_animations']['controller_variants'] = {
            'male': {'MaleWork':[[]]}, 'female': {'FemaleWork':[[]]}}
        return native

    def test_gender_branches_validate_against_the_executing_controller(self):
        model = source('''<Root><HasGenderCheck Gender="&quot;Male&quot;" SoulWUID="&quot;this.id&quot;">
          <Then><Sequence><PlayAnimation animation="&quot;MaleWork&quot;"/></Sequence></Then>
          <Else><PlayAnimation animation="&quot;FemaleWork&quot;"/></Else>
          </HasGenderCheck></Root>''')
        files, _, report = convert_behaviors([model], 'Imported', self.gender_catalog())
        self.assertEqual(report['whole_trees_emitted'], 1)
        root = E.fromstring(next(iter(files.values())))
        self.assertEqual(root.find('.//Then//AnimationAction').get('fragment'), "'MaleWork'")
        self.assertEqual(root.find('.//Else//AnimationAction').get('fragment'), "'FemaleWork'")

    def test_another_actor_gender_does_not_prove_animation_controller(self):
        for target in ('__player','workTarget'):
            model = source('<Root><HasGenderCheck Gender="&quot;Male&quot;" SoulWUID="&quot;'+target+
                '&quot;"><Then><PlayAnimation animation="&quot;MaleWork&quot;"/></Then></HasGenderCheck></Root>')
            self.assertFalse(convert_behaviors([model], 'Imported', self.gender_catalog())[0])

    def test_controller_proof_does_not_escape_conditional_branch(self):
        model = source('''<Root><Sequence><HasGenderCheck Gender="&quot;Male&quot;" SoulWUID="&quot;this.id&quot;">
          <Then><PlayAnimation animation="&quot;MaleWork&quot;"/></Then></HasGenderCheck>
          <PlayAnimation animation="&quot;MaleWork&quot;"/></Sequence></Root>''')
        self.assertFalse(convert_behaviors([model], 'Imported', self.gender_catalog())[0])

    def test_wrong_gender_branch_is_still_rejected(self):
        model = source('''<Root><HasGenderCheck Gender="&quot;Male&quot;" SoulWUID="&quot;this.id&quot;">
          <Else><PlayAnimation animation="&quot;MaleWork&quot;"/></Else></HasGenderCheck></Root>''')
        self.assertFalse(convert_behaviors([model], 'Imported', self.gender_catalog())[0])

    def test_object_and_helper_alignment_are_preserved_together(self):
        native = native_catalog()
        native['nodes']['AnimationAction']['attributes'].append('alignHelper')
        model = source('''<Root><PlayAnimation animation="&quot;CommonWork&quot;"
            SmartObject="&quot;station&quot;" HelperID="&quot;entryHelper&quot;"/></Root>''')
        files, _, report = convert_behaviors([model], 'Imported', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        node = E.fromstring(next(iter(files.values()))).find('.//AnimationAction')
        self.assertEqual(node.get('alignObject'), '$station')
        self.assertEqual(node.get('alignHelper'), '$entryHelper')
        native['nodes']['AnimationAction']['attributes'].remove('alignHelper')
        self.assertFalse(convert_behaviors([model], 'Imported', native)[0])

    def test_explicit_fragment_tag_combination_is_preserved(self):
        native = native_catalog()
        native['work_animations']['common_human_variants'] = {'CommonWork': [['left', 'tool']]}
        model = source('<Root><PlayAnimation animation="&quot;CommonWork&quot;" tags="&quot;tool+left&quot;"/></Root>')
        files, _, _ = convert_behaviors([model], 'Imported', native)
        node = E.fromstring(next(iter(files.values()))).find('.//AnimationAction')
        self.assertEqual(node.get('tags'), "'left,tool'")
        for tags in ('tool', 'tool+right', '$tags'):
            model = source(f'<Root><PlayAnimation animation="&quot;CommonWork&quot;" tags="&quot;{tags}&quot;"/></Root>')
            self.assertFalse(convert_behaviors([model], 'Imported', native)[0])

    def test_reuses_fragment_at_original_sequence_position(self):
        model = source('''<Root><Sequence><PlayAnimation animation="&quot;CommonWork&quot;"
          tags="&quot;&quot;" context="&quot;&quot;" keepContext="&quot;false&quot;"
          InterruptSafeStart="&quot;AUTO&quot;" SlavedObject="&quot;&quot;"
          ClearSlaveAnimOnExit="&quot;true&quot;" AnimationWUID="&quot;&quot;"
          SmartObject="&quot;&quot;" HelperID="&quot;&quot;"/>
          <Wait duration="&quot;6s&quot;" timeType="&quot;GameTime&quot;"/></Sequence></Root>''')
        files, _, report = convert_behaviors([model], 'Imported', native_catalog())
        seq = E.fromstring(next(iter(files.values()))).find('.//Sequence')
        self.assertEqual([e.tag for e in seq], ['AnimationAction', 'Wait'])
        self.assertEqual(seq[0].get('fragment'), "'CommonWork'")
        self.assertEqual(seq[1].get('duration'), "'6s'")
        self.assertEqual(report['whole_trees_emitted'], 1)

    def test_does_not_drop_events_alignment_or_context_to_force_conversion(self):
        for field, value in [('AnimationWUID', 'action'), ('HelperID', 'helper'), ('context', 'busy'),
                             ('tags', 'tool'), ('SlavedObject', 'bellows'), ('keepContext', 'true'),
                             ('animation', 'MissingWork')]:
            node = E.Element('PlayAnimation', animation='CommonWork')
            node.set(field, value)
            model = source('<Root>' + E.tostring(node, encoding='unicode') + '</Root>')
            files, _, report = convert_behaviors([model], 'Imported', native_catalog())
            self.assertFalse(files, field)
            self.assertEqual(report['blocked_trees'], 1)

    def test_catalog_requires_body_animation_on_both_human_controllers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Data'
            path.mkdir()
            common = '<CommonWork><Fragment Tags=""><AnimLayer><Animation name="work"/></AnimLayer></Fragment></CommonWork>'
            with zipfile.ZipFile(path / 'Animations.pak', 'w') as z:
                for index, name in enumerate(DATABASES):
                    extra = ('<OnlyOne><Fragment><AnimLayer><Animation name="one"/></AnimLayer></Fragment></OnlyOne>'
                             if index == 0 else '')
                    z.writestr(name, '<AnimDB><FragmentList>' + common + extra +
                        '<OnlyProcedural><Fragment><ProcLayer/></Fragment></OnlyProcedural>'
                        '<TaggedOnly><Fragment Tags="Special"><AnimLayer><Animation name="special"/></AnimLayer></Fragment></TaggedOnly>'
                        '<FragmentTagged><Fragment FragTags="tool"><AnimLayer><Animation name="special"/></AnimLayer></Fragment></FragmentTagged>'
                        '</FragmentList></AnimDB>')
            result = fragment_catalog(directory)
            self.assertEqual(result['common_human_fragments'], ['CommonWork'])
            self.assertEqual(result['common_human_variants']['FragmentTagged'], [['tool']])
            self.assertIn('OnlyOne', result['controller_variants']['male'])
            self.assertNotIn('OnlyOne', result['controller_variants']['female'])
            self.assertEqual(len(result['provenance']), 2)


if __name__ == '__main__':
    unittest.main()
