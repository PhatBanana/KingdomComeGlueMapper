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
                        '</FragmentList></AnimDB>')
            result = fragment_catalog(directory)
            self.assertEqual(result['common_human_fragments'], ['CommonWork'])
            self.assertEqual(len(result['provenance']), 2)


if __name__ == '__main__':
    unittest.main()
