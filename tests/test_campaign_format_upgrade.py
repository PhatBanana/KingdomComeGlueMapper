from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_polylogue import adapt, MODULE, TRIGGER
from campaign_place_markers import bind


class FormatUpgradeTests(unittest.TestCase):
    def test_separate_place_marker_preserves_counted_asset_and_repeats_safely(self):
        project=b'<Database><Skald><Project Name="demo"><Assets/></Project></Skald></Database>'
        quest=b'<Database><Skald><Quest><Objectives><Objective Name="collect"><Logs><EnumLog Type="Started"/><EnumLog Type="Completed"/></Logs></Objective></Objectives></Quest></Skald></Database>'
        objects=b'<Objects><Entity Name="demo" EntityGuid="00000001-0000-0001" EntityId="1"/></Objects>'
        waiting=b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'
        model=dict(quest='demo',tables=dict(quest_place=dict(rows=[dict(quest_asset_id='x',entity='authored',map='',show_as_area='False')]),
            quest_objective=dict(rows=[dict(objective_id='a',objective_name='collect')]),
            quest_tracked_asset=dict(rows=[dict(objective_id='a',quest_asset_id='item',map_asset_id='x',on_map='True',count='3',pos='999,888,0')])) )
        entities=[E.fromstring('<Entity Name="authored" EntityGuid="1000000000000002" EntityClass="TagPoint" Pos="1,2,3"/>')]
        p,q,o,w,r=bind(project,quest,objects,waiting,model,entities)
        self.assertEqual(r['converted'][0]['position'],'1,2,3')
        self.assertNotIn(b'999',o)
        self.assertIsNone(E.fromstring(q).find(".//EnumLog[@Type='Completed']").get('Marker'))
        self.assertEqual(model['tables']['quest_tracked_asset']['rows'][0]['count'],'3')
        self.assertEqual(bind(p,q,o,w,model,entities)[:4],(p,q,o,w))
        entities.append(E.fromstring('<Entity Name="authored" EntityGuid="1000000000000003" EntityClass="TagPoint" Pos="4,5,6"/>'))
        with self.assertRaisesRegex(ValueError,'ambiguous'):bind(p,q,o,w,model,entities)

    def test_polylogue_uses_explicit_silent_participant_and_source_gate(self):
        files={'entry.xml':b'<Database><Skald><Level><Definitions/><Nodes><chat Name="chat"><Edge From="quest.started" To="active"/><Edge From="quest.done" To="done"/></chat></Nodes></Level></Skald></Database>',
            'chat.xml':b'''<Database><Skald><FaderDialog Name="chat"><Ports><Port Name="active" Direction="In" Type="bool"/><Port Name="done" Direction="In" Type="bool"/></Ports><Dialogue Initiator="Player"><Decision><Sequences><Sequence Name="source_8" EntryCondition="Port('active') AND !Port('done') AND !SequenceUsed('source_8')" ExitScript="original_effect()"><Elements><Response Role="HENRY"/><Response Role="ONE"/></Elements></Sequence></Sequences></Decision></Dialogue></FaderDialog></Skald></Database>'''}
        templates={MODULE:b'<Database><Skald><Module Name="SpeakTrigger"><Ports/><Definitions><Definition File="SpeakTrigger/speaktrigger.xml"/></Definitions><Nodes><speaktrigger Name="speaktrigger"/></Nodes></Module></Skald></Database>',
            TRIGGER:b'<Database><Skald><Dialog Name="speaktrigger"><Ports/><Dialogue><Decision><Sequences><Sequence><Elements><Response Role="HRAC"/><Response Role="SPEAKTRIGGER_SPEAKER_SCRIPT"/></Elements></Sequence></Sequences></Decision></Dialogue></Dialog></Skald></Database>'}
        out,changed=adapt(files,'entry.xml','chat.xml',['first-soul','silent-soul'],templates)
        self.assertTrue(changed)
        host=E.fromstring(out['entry.xml'])
        self.assertEqual(host.find('.//SoulAsset').get('SharedSoulGuids'),'first-soul silent-soul')
        self.assertIsNotNone(host.find(".//Edge[@To='EnqueueDialogue']"))
        self.assertIn(b'original_effect()',out['chat.xml'])
        self.assertIn(b'ForcedDialog',out['chat.xml'])
        self.assertIn(b"!Port('done')",out['chat_source_participants/interaction.xml'])
        again,changed=adapt(out,'entry.xml','chat.xml',['first-soul','silent-soul'],templates)
        self.assertFalse(changed);self.assertEqual(out,again)


if __name__=='__main__':unittest.main()
