import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_combat_automation import lower, observe
from campaign_behavior import convert_behaviors
from campaign_quest_bridge import UnsupportedOperation
from quest_import import ast
from test_campaign_behavior import source, catalog


def native():
    result = catalog()
    result['combat_automation'] = {}
    for text in (
        '<MeleeGuardAutomationDecorator GuardMode="automate" active="true"/>',
        '<MeleeGuardAutomationDecorator GuardMode="freeBlock" active="true"/>',
        '<MeleeGuardAutomationDecorator GuardMode="forceEnable" active="true"/>',
        '<MeleeDefenseAutomationDecorator active="true"/>',
        '<MeleeOffenseAutomationDecorator active="true"/>',
        '<WeaponAutomationDecorator WeaponChange="none" active="true"/>',
    ):
        node = E.fromstring(text)
        observe(node, result['combat_automation'])
        result['nodes'][node.tag] = dict(attributes=list(node.attrib), children=['Wait'])
    return result


class CombatAutomationTests(unittest.TestCase):
    def test_supported_controls_stay_running_until_parent_cancels(self):
        for text in ('<MeleeGuardAutomation GuardMode="Automate"/>',
                     '<MeleeDefenseAutomation/>', '<MeleeOffenseAutomation/>',
                     '<WeaponAutomation WeaponChange="none" noAnimation="false"/>'):
            with self.subTest(text=text):
                source_node = ast(E.fromstring(text))
                before = copy.deepcopy(source_node)
                node = lower(source_node, native())
                self.assertEqual(node.tag, source_node['op'] + 'Decorator')
                self.assertEqual(node.get('active'), 'true')
                self.assertEqual([n.tag for n in node], ['Wait'])
                self.assertEqual(node[0].get('duration'), "'-1'")
                self.assertEqual(node[0].get('doFail'), 'false')
                self.assertNotIn('skipInLOD', node[0].attrib)
                self.assertEqual(source_node, before)

    def test_compiler_retains_timer_guard_cleanup_and_unrelated_quest_names(self):
        for quest in ('q_alternative_training', 'q_guard_duel'):
            model = source('''<Root><Behavior><FuseBox StatusPropagation="Child" OneCleanup="true">
              <Child><Parallel successMode="Any" failureMode="Any">
                <ExternalLock SemaphoreName="exercise_start" RunLogic="Halt">
                  <MeleeGuardAutomation GuardMode="Automate"/>
                </ExternalLock>
                <WeaponAutomation WeaponChange="none" noAnimation="false"/>
                <Wait duration="15s" timeType="GameTime" doFail="false" variation=""/>
              </Parallel></Child>
              <OnSuccess><Expression expressions="$hasStarted = true"/></OnSuccess>
              <OnFail><Expression expressions="$hasStarted = false"/></OnFail>
            </FuseBox></Behavior></Root>''', name=quest)
            before = copy.deepcopy(model)
            files, _, report = convert_behaviors([model], 'Imported', native())
            self.assertEqual(report['whole_trees_emitted'], 1)
            self.assertFalse(report['runtime_validated'])
            root = E.fromstring(next(iter(files.values())))
            parallel = root.find('.//Parallel')
            self.assertEqual(parallel.attrib, dict(successMode='Any', failureMode='Any'))
            self.assertEqual([n.tag for n in parallel],
                             ['ExternalLock', 'WeaponAutomationDecorator', 'Wait'])
            self.assertIsNotNone(parallel.find('./ExternalLock/MeleeGuardAutomationDecorator/Wait'))
            self.assertEqual(parallel.find('./Wait').get('duration'), "'15s'")
            self.assertIsNotNone(root.find('.//FuseBox/OnSuccess/Expression'))
            self.assertIsNotNone(root.find('.//FuseBox/OnFail/Expression'))
            self.assertEqual(model, before)

    def test_unsupported_modes_fields_and_children_are_not_discarded(self):
        invalid = ('<MeleeGuardAutomation/>', '<MeleeGuardAutomation GuardMode="Unknown"/>',
                   '<MeleeGuardAutomation GuardMode="$mode"/>',
                   '<MeleeDefenseAutomation force="true"/>',
                   '<MeleeOffenseAutomation><Success/></MeleeOffenseAutomation>',
                   '<WeaponAutomation WeaponChange="melee" noAnimation="false"/>',
                   '<WeaponAutomation WeaponChange="none" noAnimation="true"/>',
                   '<WeaponAutomation WeaponChange="none"/>')
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(UnsupportedOperation):
                lower(ast(E.fromstring(text)), native())

    def test_missing_native_mode_or_attribute_evidence_blocks_output(self):
        for change in ('mode', 'active', 'contract', 'wait', 'all'):
            cat = native()
            if change == 'mode': cat['combat_automation']['MeleeGuardAutomationDecorator']['GuardMode'] = []
            if change == 'active': cat['combat_automation']['MeleeGuardAutomationDecorator']['active'] = ['false']
            if change == 'contract': cat['nodes']['MeleeGuardAutomationDecorator']['attributes'] = []
            if change == 'wait': cat['nodes'].pop('Wait')
            if change == 'all': cat.pop('combat_automation')
            with self.subTest(change=change), self.assertRaises(UnsupportedOperation):
                lower(ast(E.fromstring('<MeleeGuardAutomation GuardMode="Automate"/>')), cat)

    def test_one_unsupported_control_withholds_complete_exercise(self):
        model = source('''<Root><Parallel successMode="Any" failureMode="Any">
          <MeleeGuardAutomation GuardMode="Automate"/>
          <PlayerCombatControls Movement="true"/>
          <Wait duration="15s"/>
        </Parallel></Root>''')
        files, _, report = convert_behaviors([model], 'Imported', native())
        self.assertFalse(files)
        self.assertEqual(report['blocked_trees'], 1)
        self.assertTrue(any('PlayerCombatControls' in error['reason']
                            for error in report['trees'][0]['unresolved']))


if __name__ == '__main__':
    unittest.main()
