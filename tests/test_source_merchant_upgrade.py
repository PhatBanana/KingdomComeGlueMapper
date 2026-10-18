import sys
import unittest
import xml.etree.ElementTree as E
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from region_travel_services import resolve_stock
from character_station_work import recognize,resources


class SourceMerchantTests(unittest.TestCase):
    def test_false_default_on_still_supplies_source_stock(self):
        shop=dict(shop_id='83',shop_type_id='4',amount_multiplier='2',amount_multiplier_random_add='0')
        rows=[dict(shop_type_id='4',item_id='commodity',amount='5',default_on='False'),
              dict(shop_type_id='4',item_id='money',amount='20',default_on='True'),
              dict(shop_type_id='5',item_id='unrelated',amount='99',default_on='True')]
        self.assertEqual(resolve_stock(shop,rows,[]),dict(commodity=10,money=40))
        self.assertEqual(resolve_stock(shop,rows,[dict(shop_id='83',item_id='commodity',amount_multiplier='0')]),dict(money=40))

    def station(self):
        return E.fromstring('''<BehaviorTree name="arbitrary_job"><Root><Behavior><Sequence>
          <GraphSearch Origin="__object.id" depth="1" selection="true" includeOrigin="false">
            <LinkDataFilter tag="Workplace" condition="$Workplace == 'standHere'" Parent="" Child="point" Data=""/>
          </GraphSearch>
          <ExactMove destinationSpecification="point" directionSpecification="point" directionType="AlignWithEntity" speed="Walk"/>
          <Wait duration="-1" timeType="GameTime" doFail="false" variation="" skipInLOD="false"/>
        </Sequence></Behavior></Root></BehaviorTree>''')

    def test_station_preserves_authored_move_alignment_and_infinite_wait(self):
        contract=recognize(self.station())
        self.assertEqual((contract['tag'],contract['value']),('Workplace','standHere'))
        _,files=resources(contract)
        tree=E.fromstring(next(b for n,b in files.items() if n.startswith('AI/')))
        self.assertEqual(tree.find('.//ExactMove').get('directionSpecification'),'$__object.id')
        self.assertEqual(tree.find('.//Wait').get('duration'),"'-1'")
        self.assertFalse(any(n.tag in ('Lua','Teleport','GiveItem','SetObjectiveState') for n in tree.iter()))

    def test_more_complex_source_work_is_not_silently_replaced(self):
        for change in ('extra','different_destination','finite_wait','side_effect'):
            tree=self.station()
            if change=='extra':E.SubElement(tree.find('.//Sequence'),'Loop')
            elif change=='different_destination':tree.find('.//ExactMove').set('destinationSpecification','other')
            elif change=='finite_wait':tree.find('.//Wait').set('duration','20')
            else:E.SubElement(tree.find('Root'),'OnInit')
            self.assertIsNone(recognize(tree),change)

if __name__=='__main__':unittest.main()
