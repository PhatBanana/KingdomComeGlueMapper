import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_branch_resume import lower


def fixture():
    files = {'Quests/root.xml': b'''<Database><Skald><Level><Definitions>
      <Definition File="a.xml"/><Definition File="b.xml"/></Definitions><Assets>
      <SoulAsset Name="a_source_participants" SharedSoulGuids="one two"/>
      <SoulAsset Name="b_source_participants" SharedSoulGuids="two one"/></Assets><Nodes>
      <quest Name="quest"><Edge From="a.finish" To="complete_stage"/></quest>
      <a Name="a"><Edge From="quest.stage_Completed" To="done"/></a>
      <b Name="b"><Edge From="quest.stage_Completed" To="done"/></b>
      </Nodes></Level></Skald></Database>''',
      'Quests/a.xml': b'''<Database><Skald><ForcedDialog Name="a"><Ports/>
      <Dialogue><Decision Alias="alpha"><Sequences><Sequence Name="seq_10"
      EntryCondition="!(Port('done'))"><Triggers><Port Name="finish"/></Triggers>
      <Elements><Response Role="ONE"><Text StringName="original_voice"/></Response></Elements>
      </Sequence></Sequences></Decision></Dialogue></ForcedDialog></Skald></Database>''',
      'Quests/b.xml': b'''<Database><Skald><ForcedDialog Name="b"><Ports/>
      <Dialogue><Decision Alias="beta"><Sequences><Sequence Name="seq_20"
      EntryCondition="Port('done') AND !SequenceUsed('seq_20')" EndType="EndDialogue"
      ExitScript="original_transfer()"/></Sequences></Decision></Dialogue></ForcedDialog></Skald></Database>'''}
    return files, {'alpha':'1','beta':'2'}, {
        '1':dict(branch_type_id='0',priority='1'), '2':dict(branch_type_id='0',priority='2')}, {
        '10':dict(flags='0',next='0'), '20':dict(flags='1',next='0')}


class BranchResumeTests(unittest.TestCase):
    def test_return_waits_for_scene_and_rechecks_source_prerequisite(self):
        f,t,b,s=fixture(); changes, report=lower(f,t,b,s)
        self.assertEqual(len(report),1)
        root=E.fromstring(changes['Quests/root.xml'])
        self.assertIsNotNone(root.find(".//SceneFinishedWaiter/Edge[@From='a.gm_return_to_source_root']"))
        self.assertIsNotNone(root.find(".//Edge[@From='a_source_root_resume.OnFinished']"))
        self.assertIsNotNone(root.find(".//Edge[@From='quest.stage_Completed']"))
        self.assertIsNotNone(root.find(".//b/Edge[@To='EnqueueDialogue']"))
        self.assertNotIn('Quests/b.xml', changes)  # effects/history/audio stay owned by source
        self.assertIn(b'original_voice',changes['Quests/a.xml'])
        f.update(changes); self.assertEqual(lower(f,t,b,s),({},[]))

    def test_ending_dialogue_or_noninvalidating_question_is_not_chained(self):
        for variant in ('source_end','native_end','no_effect','or_gate'):
            f,t,b,s=fixture()
            if variant=='source_end':s['10']['flags']='1'
            if variant=='native_end':f['Quests/a.xml']=f['Quests/a.xml'].replace(b'Name="seq_10"',b'Name="seq_10" EndType="EndDialogue"')
            if variant=='no_effect':f['Quests/a.xml']=f['Quests/a.xml'].replace(b'<Port Name="finish"/>',b'')
            if variant=='or_gate':f['Quests/a.xml']=f['Quests/a.xml'].replace(b"!(Port('done'))",b"!(Port('done')) OR true")
            self.assertEqual(lower(f,t,b,s)[0],{},variant)

    def test_unrelated_speakers_or_nonmandatory_successor_is_not_chained(self):
        f,t,b,s=fixture();b['2']['priority']='0'
        self.assertEqual(lower(f,t,b,s)[0],{})
        b['2']['priority']='2';f['Quests/root.xml']=f['Quests/root.xml'].replace(b'SharedSoulGuids="two one"',b'SharedSoulGuids="third fourth"')
        self.assertEqual(lower(f,t,b,s)[0],{})


if __name__=='__main__':unittest.main()
