import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from world_music import namespace, gate, scene_blocks, bridge


class MusicTests(unittest.TestCase):
    def test_namespace_preserves_variable_scope_and_operators(self):
        self.assertEqual(namespace('[%#town $on =] [%@playing #1 !] [%&priority %daytime !]'),
                         '[%#gm_town $on =] [%@gm_playing #1 !] [%&gm_priority %gm_daytime !]')

    def test_gate_changes_only_scene_eligibility(self):
        body='SCENE TEST/A\nN GROUP\nE [#1]\nP [#2]\nS 1 SEAMLESS 1\nE [%pattern]\nM 1 0 10 20\nEND\n'
        changed=gate(body,'[%world]')
        self.assertIn('E [[#1] [%world] &]',changed)
        self.assertIn('E [%pattern]\nM 1 0 10 20',changed)
        self.assertEqual(changed.split('P [#2]',1)[1],body.split('P [#2]',1)[1])

    def test_requires_explicit_scene_eligibility(self):
        with self.assertRaises(ValueError):gate('SCENE X\nEND\n','[%world]')

    def test_continuation_cannot_leak_across_worlds(self):
        self.assertIn('e [[%playing] [%world] &]',gate('E [#1]\ne [%playing]\nS 1 SEAMLESS 0\n','[%world]'))
        self.assertIn('e [%world]',gate('E [#1]\nS 1 SEAMLESS 0\n','[%world]'))

    def test_scene_split_preserves_macro_header(self):
        header='MACRO SKIRMISH_UPDATE\nEND\nUPDATE\nEND\n'
        h,scenes=scene_blocks(header+'SCENE A\nE [#1]\nEND\nSCENE B\nE [#0]\nEND\n')
        self.assertEqual(h,header)
        self.assertEqual([s[0] for s in scenes],['A','B'])

    def test_area_inputs_reset_on_leaving(self):
        text=bridge({'gm_location_ska':('location','ska'),'gm_river_positive':('river','++')})
        self.assertLess(text.index('[%gm_location $off !]'),text.index('IF [%#gm_location_ska]'))
        self.assertLess(text.index('[%gm_river #0 !]'),text.index('IF [%#gm_river_positive]'))
        self.assertIn('[%gm_river #1 !]',text)
        self.assertIn('IF [%#menu %#menu_title ||]',text)


if __name__=='__main__':unittest.main()
