import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from horse_trader_dialogue import dialogue
from getting_started_dialogue import attach, PATH


class IntroductionTests(unittest.TestCase):
    def test_introduction_returns_to_shop_without_buying(self):
        original,_=dialogue([dict(name='horse_a',display_name='Boxer')],'seller')
        resources,strings=attach({PATH:original})
        root=ET.fromstring(resources[PATH])
        intro=root.find(".//Sequence[@Name='getting_started_intro']")
        self.assertEqual(intro.get('EntryCondition'),"Port('getting_started_active')")
        self.assertEqual(intro.get('EndType'),'GoTo')
        self.assertEqual(intro.get('GoToDecision'),'horses')
        self.assertEqual(intro.find('Triggers/Port').get('Name'),'getting_started_talked')
        self.assertNotIn('DoMoneyTransaction',ET.tostring(intro,encoding='unicode'))
        self.assertEqual(len(intro.findall('Elements/Response/Text')),2)
        # Actual purchase is still present and still charges through native flow.
        buy=root.find(".//Sequence[@Name='buy_h00']")
        self.assertIn('Shops.DoMoneyTransaction',buy.get('ExitScript'))
        self.assertIsNone(root.find(".//Sequence[@Name='horse_advice']/Triggers"))


if __name__=='__main__':unittest.main()
