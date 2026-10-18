import sys, unittest, xml.etree.ElementTree as E
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_merchant_work import hours,add_trade_dialogue
from region_travel_merchant import dialogue, repair_trade_prompts

class MerchantWorkTests(unittest.TestCase):
    def test_merged_trade_entry_has_visible_prompt_and_old_packages_migrate(self):
        current=dialogue('any_keeper',role='ANY_ROLE',name='any_service',diagnostics=False)
        root=E.fromstring(current)
        entry=root.find('.//Dialogue/Decision/Sequences/Sequence')
        self.assertEqual(entry.find('UiPrompt').get('StringName'),'ui_gmtravel_rattay_trade')
        entry.remove(entry.find('UiPrompt'))
        legacy=E.tostring(root)
        repaired=repair_trade_prompts(legacy)
        self.assertEqual(repair_trade_prompts(repaired),repaired)
        fixed=E.fromstring(repaired)
        prompt=fixed.find('.//Dialogue/Decision/Sequences/Sequence/UiPrompt')
        self.assertEqual(prompt.get('Text'),'(Trade)')
        fixed.find('.//Dialogue/Decision/Sequences/Sequence').remove(prompt)
        self.assertEqual(E.tostring(fixed),legacy)
        path='Quests/Test/level.xml'
        resources={path:b'<Database><Skald><Level><Nodes/><Definitions/></Level></Skald></Database>',
                   'Quests/Test/source_inn_trade.xml':legacy}
        migrated=add_trade_dialogue(resources,path,'any_keeper','ANY_ROLE','source_inn')
        self.assertEqual(migrated['Quests/Test/source_inn_trade.xml'],repaired)
        self.assertEqual(resources['Quests/Test/source_inn_trade.xml'],legacy)

    def test_prompt_migration_preserves_authored_prompts_and_unrelated_choices(self):
        data=dialogue('any_keeper',diagnostics=False)
        self.assertEqual(repair_trade_prompts(data),data)
        root=E.fromstring(data)
        entry=root.find('.//Dialogue/Decision/Sequences/Sequence')
        entry.remove(entry.find('UiPrompt'))
        E.SubElement(entry.find('./Decision/Sequences'),'Sequence',Name='quest_choice',EndType='Decision')
        unrelated=E.tostring(root)
        self.assertEqual(repair_trade_prompts(unrelated),unrelated)

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
