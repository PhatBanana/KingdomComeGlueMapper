from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_state_dependencies import scan
from campaign_dependencies import DependencyImporter
from test_campaign_behavior import source
from test_campaign_buffs import adapter, ID


class StateDependencyTests(unittest.TestCase):
    def test_preflight_keeps_conditions_and_ignores_disconnected_nodes(self):
        m = source('<Root><IfCondition condition="&quot;$hasStarted&quot;"><AddBuff BuffGUID="&quot;' + ID + '&quot;" SoulWUID="&quot;actor&quot;"/></IfCondition></Root>')
        tree = m['behavior_documents']['libs/ai/quests/q_test.xml']['trees']['onUpdate']
        tree['disconnected'] = [dict(op='AddBuff', attributes=dict(BuffGUID='missing'), children=[])]
        report = scan(m, DependencyImporter(dict(buffs=adapter())))
        self.assertEqual(len(report['sites']), 1)
        site = report['sites'][0]
        self.assertEqual(site['ancestors'][-1]['operation'], 'IfCondition')
        self.assertEqual(site['dependency']['target'], ID)
        self.assertEqual(len(report['persistent_variables']), 1)
        self.assertFalse(report['executable'])


if __name__ == '__main__': unittest.main()
