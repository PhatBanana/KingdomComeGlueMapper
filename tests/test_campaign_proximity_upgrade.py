import sys
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_proximity_upgrade import upgrade
from test_campaign_proximity_dialogue import source


class UpgradeTests(unittest.TestCase):
    def test_discovers_arbitrary_source_actor_alias_and_quest_idempotently(self):
        sid='11111111-2222-3333-4444-555555555555'
        files={
            'Quests/test.xml':b'<Database><Skald><Quest Name="someQuest"><Nodes><Output Name="Output"><Edge From="objective_1.Started" To="someObjective_Started"/></Output></Nodes></Quest></Skald></Database>',
            'Quests/level.xml':f'<Database><Skald><Level><Assets><SoulAsset Name="player" SharedSoulGuids="{sid}"/></Assets></Level></Skald></Database>'.encode(),
            'Quests/speech.xml':b'<Database><Skald><Dialog><Dialogue><Decision Alias="otherGreeting"/></Dialogue></Dialog></Skald></Database>',
            'Libs/Tables/rpg/soul__test.xml':f'<Root><soul soul_id="{sid}"/></Root>'.encode()}
        controller=E.Element('Trees');controller.append(source())
        rows={'text/topic':[dict(label='otherGreeting',topic_id='99')],
              'text/topictorole':[dict(topic_id='99',role_id='78')],
              'rpg/soul2role':[dict(role_id='78',soul_id=sid)],
              'rpg/role':[dict(role_id='78',metarole_id='4')],
              'rpg/metarole':[dict(metarole_id='4',metarole_name='NPC')]}
        reader=MagicMock();reader.return_value={'controller':{'data':E.tostring(controller)}}
        tables=MagicMock();tables.get.side_effect=lambda key:dict(rows=rows[key])
        with patch('campaign_proximity_upgrade.RetailSourceReader') as factory, patch('campaign_proximity_upgrade.SourceTables',return_value=tables):
            factory.return_value.__enter__.return_value=reader
            changes,report=upgrade(files,Path('unused'))
            self.assertEqual(report[0]['speaker'],sid)
            self.assertEqual(report[0]['status'],'installed')
            self.assertIn('Quests/test.xml',changes)
            files.update(changes)
            again,_=upgrade(files,Path('unused'))
            self.assertEqual(again,{})
