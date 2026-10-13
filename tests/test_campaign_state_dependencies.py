from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_state_dependencies import scan
from campaign_dependencies import DependencyImporter
from test_campaign_behavior import source
from test_campaign_buffs import adapter, ID


class StateDependencyTests(unittest.TestCase):
    def test_lua_state_sites_distinguish_lowering_from_runtime_installation(self):
        m = source('''<Root><IfCondition condition="&quot;$hasStarted&quot;"><Sequence>
          <ExecuteLua code="&quot;player.soul:SetState('hunger',40)&quot;"/>
          <ExecuteLua code="&quot;unknown_startup_call()&quot;"/>
          </Sequence></IfCondition></Root>''')
        report = scan(m, DependencyImporter({}))
        first, second = report['sites']
        self.assertEqual(first['lowering']['code'], "player.soul:SetState('hunger', 40)")
        self.assertFalse(first['lowering']['installed'])
        self.assertEqual(first['ancestors'][-2]['arguments']['condition'], '"$hasStarted"')
        self.assertIn('semantic adapter', second['unresolved'])
        self.assertFalse(report['executable'])

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
