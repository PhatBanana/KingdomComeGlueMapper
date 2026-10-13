from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_rpg_script import upgrade
from campaign_quest_bridge import UnsupportedOperation
from campaign_behavior import convert_behaviors
from test_campaign_behavior import source, catalog


class RpgScriptTests(unittest.TestCase):
    def test_source_stat_names_and_amounts_are_upgraded(self):
        for old, new in [('str', 'strength'), ('vit', 'vitality'), ('agi', 'agility'), ('spc', 'speech')]:
            result = upgrade(f"local score = player.soul:GetStatLevel('{old}');\nplayer.soul:AdvanceToStatLevel('{old}',score+2)")
            self.assertIn("GetStatLevel('" + new + "')", result)
            self.assertIn('value + 2', result)

    def test_multiple_absolute_advancements_keep_order(self):
        result = upgrade('player.soul:AdvanceToStatLevel("str", 4)\nplayer.soul:AdvanceToStatLevel("vit", 3)')
        self.assertEqual(result, "player.soul:AdvanceToStatLevel('strength', 4); player.soul:AdvanceToStatLevel('vitality', 3)")

    def test_unrelated_calls_and_changed_variables_are_not_passed_through(self):
        for code in ["player.soul:SetState('unknown',40)",
                     "player.soul:SetState('hunger',-1)",
                     "player.soul:SetState('hunger',101)",
                     "player.soul:SetState('hunger',amount)",
                     "player.soul:SetState('hunger',40); arbitrary()",
                     "player.soul:AdvanceToStatLevel('str',4); arbitrary()",
                     "player.soul:AdvanceToStatLevel('unknown',4)",
                     "local x=player.soul:GetStatLevel('str'); player.soul:AdvanceToStatLevel('vit',x+1)",
                     "local x=player.soul:GetStatLevel('str'); player.soul:AdvanceToStatLevel('str',y+1)"]:
            with self.subTest(code=code), self.assertRaises(UnsupportedOperation): upgrade(code)

    def test_initial_states_use_source_values_and_order(self):
        self.assertEqual(upgrade("player.soul:SetState('hunger',  40)"),
                         "player.soul:SetState('hunger', 40)")
        self.assertEqual(upgrade('player.soul:SetState("exhaust", 72.5); player.soul:SetState("health", 80)'),
                         "player.soul:SetState('exhaust', 72.5); player.soul:SetState('health', 80)")

    def test_state_initialization_cannot_escape_guard_or_blocked_sibling(self):
        c = catalog()
        c['nodes']['ExecuteLua'] = dict(attributes=['code'], children=[])
        m = source('''<Root><IfCondition condition="&quot;$hasStarted&quot;"><Sequence>
          <ExecuteLua code="&quot;player.soul:SetState('hunger', 40)&quot;"/>
          <Expression expressions="&quot;$hasStarted = true&quot;"/>
          </Sequence></IfCondition></Root>''')
        files, _, report = convert_behaviors([m], 'Imported', c)
        guard = E.fromstring(next(iter(files.values()))).find('.//IfCondition')
        self.assertEqual(guard.get('condition'), '$hasStarted')
        self.assertEqual([n.tag for n in guard.find('Sequence')], ['ExecuteLua', 'Expression'])
        self.assertEqual(guard.find('./Sequence/ExecuteLua').get('code'), "player.soul:SetState('hunger', 40)")
        sequence = m['behavior_documents']['libs/ai/quests/q_test.xml']['trees']['onUpdate']['root']['children'][0]['children'][0]
        sequence['children'].append(dict(op='UnsupportedSibling', attributes={}, children=[], text=''))
        files, _, report = convert_behaviors([m], 'Imported', c)
        self.assertFalse(files)
        self.assertEqual(report['blocked_trees'], 1)

    def test_behavior_conversion_keeps_original_guard(self):
        c = catalog()
        c['nodes']['ExecuteLua'] = dict(attributes=['code'], children=[])
        m = source('''<Root><IfCondition condition="&quot;$hasStarted&quot;">
          <ExecuteLua code="&quot;player.soul:AdvanceToStatLevel('str',4)&quot;"/>
          </IfCondition></Root>''')
        files, _, report = convert_behaviors([m], 'Imported', c)
        node = E.fromstring(next(iter(files.values()))).find('.//IfCondition')
        self.assertEqual(node.get('condition'), '$hasStarted')
        self.assertIn("'strength'", node.find('ExecuteLua').get('code'))
        self.assertEqual(report['whole_trees_emitted'], 1)

    def test_quest_lock_name_scope_and_value_are_preserved(self):
        m = source('''<Root><SetExternalLock LockManagerType="&quot;Intellect&quot;"
             Locked="&quot;false&quot;" LockName="&quot;arbitraryQuestGate&quot;"/></Root>''')
        files, _, _ = convert_behaviors([m], 'Imported', catalog())
        node = E.fromstring(next(iter(files.values()))).find('.//SetExternalLock')
        self.assertEqual(node.attrib, dict(LockManagerType='Intellect', Locked='false', LockName="'arbitraryQuestGate'"))


if __name__ == '__main__': unittest.main()
