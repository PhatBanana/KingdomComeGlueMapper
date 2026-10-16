import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_profile_systems import select_people


class SliceSelectionTests(unittest.TestCase):
    def test_selected_source_actors_remain_intact(self):
        roster=[dict(name='worker',source='work-data'),dict(name='guard',source='guard-data'),dict(name='other')]
        selected=select_people(roster,['guard','worker'])
        self.assertEqual(selected,roster[:2])
        self.assertIs(selected[0],roster[0])
        self.assertIs(select_people(roster,None),roster)
        with self.assertRaises(ValueError):select_people(roster,['missing'])
        with self.assertRaises(ValueError):select_people(roster+roster[:1],['worker'])


if __name__=='__main__':unittest.main()
