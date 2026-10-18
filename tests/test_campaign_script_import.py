import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_script_import import translate, upgrade_dialogue
from campaign_actor_dialogues import remap_roles


class ScriptImportTests(unittest.TestCase):
    def test_saved_dialogue_uses_its_registered_role(self):
        blob = b'''<Database><Dialogue><Response Role="seller_28"/><Sequence ExitScript="Utils.GiveItem(dc.TRADER,player,'item',1)"/></Dialogue></Database>'''
        result, count = upgrade_dialogue(blob, [dict(role_id='28', role_name='TRADER')])
        self.assertEqual(count, 1)
        self.assertIn(b'ItemUtils.GiveItem(dc.seller_28,player', result)
        self.assertEqual(upgrade_dialogue(result, [dict(role_id='28', role_name='TRADER')]), (result, 0))

    def test_transfer_api_and_participant_follow_source_role_mapping(self):
        script = "Utils.GiveItem(dc.MERCHANT,player,'source-item',1)"
        model = dict(roles={'1': dict(role_name='MERCHANT')},
                     topics={'a': dict(sequences=[dict(source=dict(script=script))])})
        result = remap_roles(model, {'MERCHANT': 'imported_1'})
        self.assertEqual(result['topics']['a']['sequences'][0]['source']['script'],
                         "ItemUtils.GiveItem(dc.imported_1,player,'source-item',1)")
        self.assertEqual(model['topics']['a']['sequences'][0]['source']['script'], script)

    def test_literals_comments_and_other_apis_are_preserved(self):
        text = "'Utils.GiveItem' -- Utils.GiveItem(dc.MERCHANT)\n[=[dc.MERCHANT]=]; Utils.Other(); Utils.GiveItem(dc.MERCHANT,player,id,2)"
        result = translate(text, {'MERCHANT': 'imported_1'})
        self.assertEqual(result, text.rsplit('Utils.GiveItem', 1)[0] +
                         'ItemUtils.GiveItem(dc.imported_1,player,id,2)')
        self.assertEqual(translate(result, {'MERCHANT': 'imported_1'}), result)
