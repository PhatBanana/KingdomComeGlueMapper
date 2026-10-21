import copy
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_intro_factions import source_contract, attach
from campaign_temporary_factions import OPTION
from campaign_quest_graph import xml
from test_campaign_combat_runtime import Graph

SOURCE = ('''<BehaviorTrees><BehaviorTree name="onUpdate"><Root><Behavior>
<QuestCondition quest="parent" function="IsQuestCompleted"><Then><Success/></Then><Else>
<ProfileLoadedGate LayerName="village_normal" NegateTo="false" RunLogic="Halt"><Sequence>
<GraphSearch><LinkDataFilter tag="QuestActor" condition="$QuestActor == 'teacher'" Child="npc"/></GraphSearch>
<SetTemporarySuperfaction soul="npc" superfaction="Friendly"/>
</Sequence></ProfileLoadedGate></Else></QuestCondition></Behavior></Root></BehaviorTree>
<BehaviorTree name="arrival"><Variables><Variable name="phase" isPersistent="1"/></Variables>
<Root><OnInit><Sequence><IfCondition condition="$phase &lt; 10" failOnCondition="false"><Sequence>
<SetTemporarySuperfaction soul="this.id" superfaction="Friendly"/>
<ExecuteLua code="Contexts.SetPersistentOption(entity, '%s', 'lesson')"/>
</Sequence></IfCondition></Sequence></OnInit></Root></BehaviorTree></BehaviorTrees>''' % OPTION).encode()


def plan():
    p=dict(tree='arrival',parent_quest='parent',actor_role='teacher')
    p['temporary_faction']=dict(source_contract(SOURCE,p),native_faction='imported_friendly')
    return p


def entry():
    return E.fromstring('<Database><Skald><Level><Nodes><parent Name="parent_instance"/>'
                        '<State Name="example_ended" TypeT="bool"/></Nodes></Level></Skald></Database>')


class IntroFactionTests(unittest.TestCase):
    def test_generic_source_names_and_both_initializers(self):
        p=plan();c=p['temporary_faction']
        self.assertEqual((c['source_faction'],c['source_profile'],c['protection_handle']),
                         ('Friendly','village_normal','lesson'))
        other=SOURCE.replace(b'teacher',b'carpenter').replace(b'Friendly',b'Artisans')
        self.assertEqual(source_contract(other,dict(p,actor_role='carpenter'))['source_faction'],'Artisans')

    def test_effect_lifetime_does_not_follow_worker_or_combat_callbacks(self):
        r=entry();attach(r,'example',plan())
        r.find('Skald/Level').tag='Module';g=Graph(xml(r))
        effect=g.nodes['example_temporary_faction']
        ref=effect.find('Edge').get('From')
        self.assertEqual(ref,'parent_instance.started')
        for active in (False,True,False,True):
            g.values[ref]=active
            for event in ('example_enable.Success','example_enable.Fail','native_combat_started'):
                g.fire(event)
                self.assertEqual(g.value(ref),active)
        # Reconstruction reads persistent quest state, not an unsaved local latch.
        restored=Graph(xml(r));restored.values[ref]=False
        self.assertFalse(restored.value(ref))
        restored.values[ref]=True;self.assertTrue(restored.value(ref))
        self.assertEqual(effect.find('Asset').get('Alias'),'example_actor')
        self.assertFalse(r.findall('.//SetFaction'))

    def test_idempotency_and_conflicts(self):
        r=entry();p=plan();before=copy.deepcopy(r.find('.//State').attrib)
        self.assertTrue(attach(r,'example',p))
        self.assertFalse(attach(r,'example',p))
        attach(r,'example',p,validate=True)
        self.assertEqual(before,r.find('.//State').attrib)
        r.find('.//TemporaryFactionEffect/Constant').set('Value','wrong')
        with self.assertRaisesRegex(ValueError,'differs'):
            attach(r,'example',p)

    def test_missing_effect_cannot_pass_package_validation(self):
        with self.assertRaisesRegex(ValueError,'not connected'):attach(entry(),'example',plan(),validate=True)
        with self.assertRaisesRegex(ValueError,'Missing current'):
            attach(entry(),'example',dict(tree='arrival',parent_quest='parent',actor_role='teacher'),validate=True)

    def test_rejects_untranslated_clear_replace_or_protection_release(self):
        mutations=[
            SOURCE.replace(b'</BehaviorTrees>',b'<ClearTemporarySuperfaction soul="npc"/></BehaviorTrees>'),
            SOURCE.replace(b'</BehaviorTrees>',b'<SetTemporarySuperfaction soul="npc" superfaction="Hostile"/></BehaviorTrees>'),
            SOURCE.replace(b'SetPersistentOption',b'ClearOption'),
            SOURCE.replace(b'superfaction="Friendly"',b'superfaction="$dynamic"'),
            SOURCE.replace(b'isPersistent="1"',b'isPersistent="0"'),
            SOURCE.replace(b'NegateTo="false"',b'NegateTo="true"'),
            SOURCE.replace(b"$QuestActor == 'teacher'",b"$QuestActor == 'different_actor'"),
        ]
        for blob in mutations:
            with self.subTest(blob=blob),self.assertRaises(ValueError):source_contract(blob,plan())


if __name__=='__main__':unittest.main()
