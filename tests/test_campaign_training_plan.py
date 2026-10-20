import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_import import ast
from campaign_training_plan import arrival, borrowed_equipment
from campaign_quest_bridge import UnsupportedOperation


ITEM = '00000000-0000-0000-0000-000000000123'


def equipment():
    prepare = ast(E.fromstring(f'''<Root><Behavior><Sequence>
<CreateItem ItemGUID="{ITEM}" Amount="1" CreatedItem="loan" Target="this.id"/>
<EquipItem item="loan" Target="this.id"/>
</Sequence></Behavior></Root>'''))
    cleanup = ast(E.fromstring('''<Root><Behavior><Sequence>
<RemoveItem Item="loan" ItemGUID="" Amount="0" Source="this.id" FailOnDoesntExist="false"/>
</Sequence></Behavior></Root>'''))
    return prepare, cleanup


def travel():
    return ast(E.fromstring('''<Root><OnInit><GraphSearch>
<LinkDataFilter tag="QuestPlace" condition="$QuestPlace == 'arbitrary_ring'" Child="spot"/>
</GraphSearch></OnInit><Behavior><Sequence>
<QuestObjectiveCondition quest="" objective="arrive" function="IsObjectiveStarted"><Then><Sequence>
<Move destinationSpecification="spot" speed="Walk" stopWithinDistance="1"/>
<SetQuestObjective quest="" objective="arrive" function="CompleteObjective"/>
</Sequence></Then></QuestObjectiveCondition>
<CallBehavior Target="spot" BehaviorName="use"/>
</Sequence></Behavior></Root>'''))


class TrainingPlanTests(unittest.TestCase):
    def test_borrowed_items_retain_instance_ownership_and_source_order(self):
        prepare, cleanup = equipment()
        snapshot = copy.deepcopy((prepare, cleanup))
        plan = borrowed_equipment(prepare, cleanup)
        self.assertEqual(plan['leases'], [dict(handle='loan', item=ITEM, owner='actor',
            create_index=0, equip_indices=[1], remove_index=0)])
        self.assertEqual((prepare, cleanup), snapshot)
        self.assertFalse(plan['publication_ready'])

    def test_cleanup_by_type_or_wrong_owner_is_rejected(self):
        for field, value in [('ItemGUID', ITEM), ('Source', '__player'), ('Item', 'unknown'),
                             ('Amount', '1'), ('FailOnDoesntExist', 'true')]:
            prepare, cleanup = equipment()
            cleanup['children'][0]['children'][0]['children'][0]['attributes'][field] = value
            with self.subTest(field=field), self.assertRaises(UnsupportedOperation):
                borrowed_equipment(prepare, cleanup)

    def test_missing_cleanup_and_duplicate_creation_are_rejected(self):
        prepare, cleanup = equipment()
        cleanup['children'][0]['children'][0]['children'] = []
        with self.assertRaises(UnsupportedOperation): borrowed_equipment(prepare, cleanup)
        prepare, cleanup = equipment()
        body = prepare['children'][0]['children'][0]['children']
        body.append(copy.deepcopy(body[0]))
        with self.assertRaises(UnsupportedOperation): borrowed_equipment(prepare, cleanup)

    def test_conditionals_are_not_flattened_into_unconditional_equipment(self):
        prepare, cleanup = equipment()
        body = prepare['children'][0]['children'][0]['children']
        body[0] = dict(op='IfCondition', attributes={'condition':'optional'}, children=[body[0]])
        with self.assertRaises(UnsupportedOperation): borrowed_equipment(prepare, cleanup)

    def test_arrival_uses_source_place_and_preserves_entire_program(self):
        root = travel()
        plan = arrival(root)
        self.assertEqual(plan['place_role'], 'arbitrary_ring')
        self.assertEqual(plan['objective'], 'arrive')
        self.assertEqual(plan['source'], root)
        self.assertFalse(plan['publication_ready'])

    def test_arrival_cannot_complete_before_movement_or_wrong_objective(self):
        for mode in ('order', 'objective'):
            root = travel()
            body = root['children'][1]['children'][0]['children'][0]['children'][0]['children'][0]['children']
            if mode == 'order': body.reverse()
            else: body[1]['attributes']['objective'] = 'other'
            with self.subTest(mode=mode), self.assertRaises(UnsupportedOperation): arrival(root)


if __name__ == '__main__': unittest.main()
