import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_package_upgrade import eligible, finalize
from setup_campaign import MOD_ID, RECEIPT, digest, verify_package
from setup_gameplay import PROJECT, OPENING, STAGE_IDS
from campaign_scene import attach_scene
from campaign_start_policy import POLICY, validate_start_policy
from region_travel_companions import travel_player_resources


class UpgradeTests(unittest.TestCase):
    def test_migrates_legacy_world_without_changing_shared_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            def archive(name, entries):
                path=p/name;path.parent.mkdir(parents=True,exist_ok=True)
                with zipfile.ZipFile(path,'w') as z:
                    for key,value in entries.items():z.writestr(key,value)
            host=b'<Database><Skald><Project><Nodes/><Definitions/><Types/><ObjectiveValueTypes/></Project></Skald></Database>'
            source=f'<Database><Skald><Project><Nodes><Quest Name="q"/><Dialogue Name="{OPENING}"/></Nodes><Definitions/><Types/><ObjectiveValueTypes/></Project></Skald></Database>'.encode()
            graph=ET.fromstring(attach_scene(host,source,OPENING,'q','level.arrived','done','player'))
            nodes=graph.find('./Skald/Project/Nodes');nodes.remove(nodes.find('IfFunction'))
            nodes.find('TriggerSequence/Edge').set('From',OPENING+'_begin.True')
            latch=nodes.find('State');latch.remove(latch.find(f"Edge[@From='{OPENING}_new_game.False']"))
            player=travel_player_resources(b'function Player:OnInit() end\nfunction Player:OnLoadAI() end\n')['Scripts/Entities/actor/player.lua']
            player+=Path('tools/region_travel_horse_recovery.lua').read_bytes()
            archive('Data/gluemappertravel.pak',{PROJECT:ET.tostring(graph),'Scripts/Entities/actor/player.lua':player,'keep':b'unchanged'})
            archive('Data/Levels/kcd1_travel/level.pak',{'objects_mission0.xml':b'<Objects><Entity EntityClass="SmartAreaShape" EntityGuid="0000000a-0000-0000"/></Objects>', 'whdata_0':b'<Root><AI><SmartAreaManager version="2"><SmartAreas/></SmartAreaManager></AI></Root>'})
            from campaign_trigger_areas import write_areas
            with zipfile.ZipFile(p/'Data/Levels/kcd1_travel/level.pak','a') as z:
                z.writestr('triggerareas.fubar',write_areas([],1))
                from test_skalitz_outer_gates import fixture
                for name,data in fixture().items():z.writestr(name,data)
            table=f'Libs/Tables/level__{MOD_ID}.xml'
            archive(f'Data/{MOD_ID}.pak',{table:b'<Root><Levels><LevelData LevelId="2" LevelName="trosecko"/><LevelData LevelId="1000" LevelName="kcd1_rataje"/><LevelData LevelId="1001" LevelName="kcd1_travel"/></Levels></Root>'})
            (p/'mod.manifest').write_text(f'<Mod><info><modid>{MOD_ID}</modid></info></Mod>')
            (p/'campaign-audit.json').write_text('{}')
            base=p/'Data/Levels/kcd1_rataje';base.mkdir();(base/'terrain.pak').write_bytes(b'base')
            shared=p/'Data/shared.pak';shared.write_bytes(b'shared')
            r=dict(schema=1,owner=MOD_ID,travel_bridge={'destination':'kcd1_travel'},build_recipe=dict(version=3,status='complete',content_validation={'actors':11},streaming_validation={'ok':True},shader_validation={'installation':'mod_private_root'},steps=[{'id':s} for s in STAGE_IDS]))
            r['files']={f.relative_to(p).as_posix():digest(f) for f in p.rglob('*') if f.is_file()}
            (p/RECEIPT).write_text(json.dumps(r))
            eligible(r)
            with patch('setup_gameplay.validate',return_value={'start_policy':POLICY}):result=finalize(p)
            verify_package(p)
            self.assertTrue(result['single_playable_world']);self.assertFalse(base.exists())
            self.assertEqual(result['package_upgrade']['skalitz_outer_gates']['opened_leaves'],6)
            self.assertEqual(shared.read_bytes(),b'shared')
            with zipfile.ZipFile(p/'Data/gluemappertravel.pak') as z:
                validate_start_policy(z.read(PROJECT),OPENING)
                self.assertNotIn(b'GlueTravelHorseRecovery',z.read('Scripts/Entities/actor/player.lua'))
                self.assertEqual(z.read('keep'),b'unchanged')
            with zipfile.ZipFile(p/f'Data/{MOD_ID}.pak') as z:
                self.assertEqual([e.get('LevelId') for e in ET.fromstring(z.read(table)).find('Levels')],['2','1001'])
            with zipfile.ZipFile(p/'Data/Levels/kcd1_travel/level.pak') as z:
                self.assertEqual(ET.fromstring(z.read('whdata_0')).findtext('.//Guid'),'10')
            broken=json.loads(json.dumps(r));broken['build_recipe']['steps']=[]
            with self.assertRaises(ValueError):eligible(broken)
