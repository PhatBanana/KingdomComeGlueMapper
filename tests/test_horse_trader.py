"""Purchase gates and native ownership handoff must survive dialogue generation."""
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from horse_trader_dialogue import dialogue, ROLE


class HorseSalesTests(unittest.TestCase):
    def setUp(self):
        self.horses = [dict(name='source_horse_a', display_name='Boxer'),
                       dict(name='source_horse_b', display_name='Kelpie')]
        self.root = ET.fromstring(dialogue(self.horses, 'source_seller')[0])

    def test_payment_gates_purchase_and_is_in_decigroschen(self):
        for i, horse in enumerate(self.horses):
            key = f'h{i:02}'
            buy = self.root.find(f".//Sequence[@Name='buy_{key}']")
            self.assertIn(f"Port('{key}_money')", buy.get('EntryCondition'))
            self.assertIn(f"Port('{key}_available')", buy.get('EntryCondition'))
            self.assertIn(f"Ports['Payment_buy_{key}'] * 10", buy.get('ExitScript'))
            self.assertIn('Shops.DoMoneyTransaction', buy.get('ExitScript'))
            self.assertEqual(buy.find('Triggers/Port').get('Name'), key+'_buy')
            self.assertIsNotNone(self.root.find(f".//Ports/Port[@Name='Payment_buy_{key}']"))

    def test_trade_in_refund_uses_opposite_payment_direction(self):
        refund = self.root.find(".//Sequence[@Name='refund_h00']")
        self.assertIn("!Port('Payment_buy_h00')", refund.get('EntryCondition'))
        self.assertIn("Ports['Payment_refund_h00'] * -10", refund.get('ExitScript'))

    def test_back_and_exit_never_buy(self):
        for seq in self.root.findall('.//Sequence'):
            if seq.get('Name').startswith(('cancel_', 'select_')) or seq.get('Name') == 'leave':
                self.assertIsNone(seq.find('Triggers'))
                self.assertNotIn('DoMoneyTransaction', seq.get('ExitScript', ''))

    def test_no_lua_shortcut_for_ownership_or_free_spawn(self):
        text = ET.tostring(self.root, encoding='unicode')
        for unsafe in ('SetPlayerHorse', 'SpawnEntity', 'AddMoney'):
            self.assertNotIn(unsafe, text)
        selected = self.root.find(f".//SelectedSoul[@Role='{ROLE}']")
        self.assertEqual(selected.get('Soul'), 'source_seller')


if __name__ == '__main__': unittest.main()
