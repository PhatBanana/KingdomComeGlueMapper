import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_scope import bind_level
from campaign_quest_text import register_journal_strings, localization_table


class QuestScopeTests(unittest.TestCase):
    def test_level_ownership_keeps_input_and_output_connections(self):
        p = b'<Database><Skald><Project><Nodes><world Name="world"/><q Name="quest"><Edge From="scene.finished" To="complete"/></q><scene Name="scene"><Edge From="quest.active" To="ready"/></scene></Nodes></Project></Skald></Database>'
        l = b'<Database><Skald><Level Name="world"><Nodes/></Level></Skald></Database>'
        q = b'<Database><Skald><Quest Name="q"><Ports><Port Name="complete" Direction="In" Type="trigger"/><Port Name="active" Direction="Out" Type="bool"/></Ports></Quest></Skald></Database>'
        project, level, report = bind_level(p,l,q,'quest','world')
        pr, le = E.fromstring(project), E.fromstring(level)
        self.assertIsNone(pr.find('.//q'))
        self.assertEqual(le.find('.//q/Edge').attrib, dict(From='quest__complete', To='complete'))
        self.assertEqual(pr.find('.//world/Edge').attrib, dict(From='scene.finished',To='quest__complete'))
        self.assertEqual(pr.find('.//scene/Edge').get('From'), 'world.quest__active')
        self.assertEqual(le.find('.//Output/Edge').attrib, dict(From='quest.active', To='quest__active'))
        with self.assertRaises(ValueError): bind_level(project,level,q,'quest','world')
        with self.assertRaises(ValueError): bind_level(p.replace(b'quest.active',b'quest.missing'),l,q,'quest','world')

    def test_journal_text_has_registered_stable_keys_and_preserves_words(self):
        q=b'<Database><Skald><Quest Name="original"><QuestName Text="Unexpected Visit"/><Objectives><Objective Name="father"><LocalizedName Text="Go to your father"/><Logs><EnumLog Name="Started"><Log Text="Original text"/></EnumLog></Logs></Objective></Objectives></Quest></Skald></Database>'
        blob, records = register_journal_strings(q)
        keys={e.get('StringName') for e in E.fromstring(blob).iter() if e.get('Text')}
        table=E.fromstring(localization_table(records))
        self.assertEqual(keys,{row[0].text for row in table})
        self.assertEqual([row[2].text for row in table],['Unexpected Visit','Go to your father','Original text'])
        self.assertEqual(register_journal_strings(blob), (blob,records))


if __name__ == '__main__': unittest.main()
