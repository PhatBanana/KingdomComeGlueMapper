import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import tempfile
import unittest
import zipfile
from pathlib import Path
from campaign_scene_test import source_scene_positions
from setup_package_upgrade import migrate_step_ids
from setup_gameplay import STAGE_IDS, DIALOGUES


class GuardUpgrade(unittest.TestCase):
    def test_source_idle_spots_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'Data/Levels/test/level.pak';p.parent.mkdir(parents=True)
            blob=b"""<Objects><Entity Name="quest"><EntityLinks><Link Name="CutsceneSpot[npc('guard'),alias('opening'),idle(true)]" TargetId="2"/></EntityLinks></Entity><Entity Name="spot" EntityId="2" Pos="12,34,56" Rotate="1,0,0,0"/></Objects>"""
            with zipfile.ZipFile(p,'w') as z:z.writestr('objects_mission0.xml',blob)
            pose=source_scene_positions(root,'test','quest','opening')['guard']
            self.assertEqual(pose['Pos'],'12,34,56')
            self.assertEqual(pose['Rotate'],'1,0,0,0')

    def test_upgrade_preserves_stage_order_and_is_idempotent(self):
        report=dict(steps=[dict(id=s) for s in STAGE_IDS if s!='gm_guard_interaction'])
        migrate_step_ids(report)
        self.assertEqual([s['id'] for s in report['steps']],list(STAGE_IDS))
        migrate_step_ids(report)
        self.assertEqual([s['id'] for s in report['steps']],list(STAGE_IDS))

    def test_incomplete_old_recipe_is_not_masked(self):
        report=dict(steps=[dict(id='opening')])
        migrate_step_ids(report)
        self.assertEqual(report['steps'],[dict(id='opening')])

    def test_activation_uses_source_objective_instead_of_quest_names(self):
        from setup_guard_conversations import source_activation
        gate=dict(op='QuestObjectiveCondition',attributes=dict(quest='$__object.name',function='IsObjectiveStarted',objective='differentObjective'))
        model=dict(quest='otherQuest',behavior_entry='doc',behavior_documents={'doc':{'trees':{'initiator':{'root':dict(children=[dict(op='Behavior',children=[gate])])}}}},tables={'quest_objective':{'rows':[dict(objective_name='differentObjective')]}})
        self.assertEqual(source_activation(model,'initiator'),'otherQuest.differentObjective_Started')
        gate['attributes']['function']='UnknownFunction'
        with self.assertRaises(ValueError):source_activation(model,'initiator')
