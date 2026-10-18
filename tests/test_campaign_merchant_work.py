import sys, unittest, xml.etree.ElementTree as E
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_merchant_work import hours,add_trade_dialogue

class MerchantWorkTests(unittest.TestCase):
    def test_source_opening_hours_and_overnight_intervals(self):
        self.assertEqual(hours(dict(business_hours_begin='6',business_hours_end='21')),[(360,1260)])
        self.assertEqual(hours(dict(business_hours_begin='22',business_hours_end='2')),[(1320,1440),(0,120)])
        with self.assertRaises(ValueError):hours(dict(business_hours_begin='6',business_hours_end='6'))

    def test_native_trade_uses_actor_identity_without_quest_completion_effects(self):
        path='Quests/Test/level.xml'
        resources={path:b'<Database><Skald><Level><Nodes/><Definitions/></Level></Skald></Database>'}
        result=add_trade_dialogue(resources,path,'source_keeper','SOURCE_KEEPER','source_inn')
        dialog=E.fromstring(result['Quests/Test/source_inn_trade.xml'])
        self.assertEqual(dialog.find('.//SelectedSoul[@Role="SOURCE_KEEPER"]').get('Soul'),'source_keeper')
        self.assertEqual(len(dialog.findall('.//Sequence[@Type="OpenShop"]')),1)
        self.assertEqual(len(dialog.findall('.//Sequence[@Type="Shop"]')),1)
        self.assertFalse(any(n.get('ExitScript') for n in dialog.iter('Sequence')))
        self.assertNotIn(b'GMTRAVEL_RATTAY_INNKEEPER',result['Quests/Test/source_inn_trade.xml'])
        self.assertEqual(result,add_trade_dialogue(result,path,'source_keeper','SOURCE_KEEPER','source_inn'))

if __name__=='__main__':unittest.main()
