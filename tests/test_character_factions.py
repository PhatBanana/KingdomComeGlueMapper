import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_factions import capture, register, PATH, LEAF, GROUP


class FactionsTests(unittest.TestCase):
    def data(self):
        factions = [dict(faction_id='3', faction_name='merchants', superfaction_id='3', player_reputation='.5'),
                    dict(faction_id='38', faction_name='villagers', superfaction_id='3', player_reputation='1'),
                    dict(faction_id='12', faction_name='invaders', superfaction_id='1', player_reputation='-1')]
        groups = [dict(superfaction_id=k, superfaction_name=n) for k,n in
                  [('1','Invaders'),('3','Civilians'),('5','Player')]]
        return dict(faction=factions[1], superfaction=groups[1], factions=factions, superfactions=groups,
                    relationships=[dict(from_superfaction_id='1',to_superfaction_id='3',relationship='-1'),
                                   dict(from_superfaction_id='3',to_superfaction_id='1',relationship='-.5'),
                                   dict(from_superfaction_id='1',to_superfaction_id='5',relationship='-1')])

    def test_overlapping_ids_are_separate_domains_and_hostility_is_signed(self):
        data=self.data();files={};register(files,data)
        data['faction']=data['factions'][2];register(files,data)
        root=E.fromstring(files[PATH])
        self.assertIsNotNone(root.find(f".//Faction[@Name='{GROUP}3']/Children/Faction[@Name='{LEAF}38']"))
        self.assertIsNone(root.find(f".//Faction[@Name='{LEAF}3']"))
        self.assertEqual(root.find(f".//Faction[@Name='{LEAF}12']/Relations/Relation").get('reputation'),'-1')
        self.assertEqual(root.find(f".//Faction[@Name='{GROUP}3']/Relations/Relation").get('reputation'),'-.5')
        self.assertEqual(root.find(f".//Faction[@Name='{GROUP}1']/Relations/Relation[@target='player']").get('reputation'),'-1')

    def test_old_bad_hierarchy_migrates_without_losing_registered_people(self):
        files={PATH:f'<database><FactionTree><Faction Name="{LEAF}3"><Children><Faction Name="{LEAF}38"/></Children></Faction></FactionTree></database>'.encode()}
        register(files,self.data());before=files[PATH];register(files,self.data())
        self.assertEqual(before,files[PATH])
        root=E.fromstring(before)
        self.assertEqual(len(root.findall(f".//Faction[@Name='{GROUP}3']/Children/Faction")),2)
        self.assertIsNone(root.find(f".//Faction[@Name='{LEAF}3']/Children"))

    def test_invalid_relations_leave_existing_output_intact(self):
        for value in ['nan','inf','1.1','-1.1']:
            files={};data=self.data();register(files,data);before=dict(files)
            data['relationships'][0]['relationship']=value
            with self.assertRaises(ValueError):register(files,data)
            self.assertEqual(files,before)

    def test_duplicate_and_missing_relation_targets_rejected(self):
        for target in ['3','404']:
            data=self.data();data['relationships'].append(dict(data['relationships'][0],to_superfaction_id=target))
            with self.assertRaises(ValueError):register({},data)

if __name__=='__main__':unittest.main()
