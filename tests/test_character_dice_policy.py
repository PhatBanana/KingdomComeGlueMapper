import unittest
import xml.etree.ElementTree as E
from character_dice_policy import CONDITION, minimum_bet, opponent, conditional_leaning, validate_leaning, lean_program


def fixtures():
    source=E.Element('BehaviorTree');gate=E.SubElement(E.SubElement(E.SubElement(source,'Root'),'Behavior'),'LuaGate',code=CONDITION)
    for branch,target,behavior in [('Then','diceTable','diceOpponent'),('Else','leaningSpot','use')]:
        E.SubElement(E.SubElement(gate,branch),'CallBehavior',Target=target,BehaviorName=behavior)
    social='SocialClass.defaultValues = {diceMinimumBet = 17, diceMaximumBet = 1000,}'
    program=E.fromstring('''<BehaviorTrees><BehaviorTree name="use_opponent"><Root><Behavior><Decision><Exec><FuseBox><Child><Sequence>
      <NumericalOperation In1VariableName="data:script_param['dice_gameLevelBetSize_beggar'].value" OutVariableName="$amountToCheck"/>
      <Expression expressions="$amountToCheck *= 10"/>
      <Function_dice_checkMoney amountToCheck="$amountToCheck" npcHasEnough="$hasEnoughMoney"/>
      <IfCondition><Sequence><CreateItem Target="$this.id"/><Expression expressions="$hasEnoughMoney = true"/></Sequence></IfCondition>
      <IfElseCondition condition="$hasEnoughMoney"><Else><WaitAction/></Else></IfElseCondition>
    </Sequence></Child></FuseBox></Exec></Decision></Behavior></Root></BehaviorTree></BehaviorTrees>''')
    template=E.fromstring('''<SmartEntityTemplate BrainId="native-brain"><BehaviorTemplates><SmartBehaviorTemplate Name="use_opponent" InitialState="Disabled"><TreeLocation FileName="world/so_diceTable_new.xml" TreeName="use_opponent"/><Inboxes><InboxTemplate InboxId="native-inbox"/></Inboxes></SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate>''')
    return source,social,program,template


class DicePolicyTests(unittest.TestCase):
    def test_conditional_lean_does_not_replace_funded_opponent(self):
        tree=E.fromstring('''<BehaviorTree><Variables/><Root><OnInit><Sequence>
        <GraphSearch Origin="$__object.id"><LinkTagFilter tag="'cupSlot1'" Child="$cupSlot"/></GraphSearch>
        </Sequence></OnInit><Behavior><Decision name="dice_gamblerState"/></Behavior></Root></BehaviorTree>''')
        call=E.Element('CallBehavior',Target='$original',BehaviorName="'use'",ignoreDropUnloading='false')
        result=conditional_leaning(tree,17,call)
        gate=result.find('Root/Behavior/LuaGate')
        self.assertEqual(gate.get('code'),'return entity.inventory:GetMoney() >= 17')
        self.assertEqual(gate.find('Then/Decision').get('name'),'dice_gamblerState')
        calls=gate.findall('.//CallBehavior')
        self.assertEqual({c.get('Target') for c in calls},{'$gmLeanLeft','$gmLeanRight'})
        self.assertTrue(all(c.get('ignoreDropUnloading')=='false' for c in calls))
        self.assertEqual(result.find("Variables/Variable[@name='gmLeanSide']").get('isPersistent'),'1')
        self.assertEqual(result.find('.//RandomGate').get('opensWithChance'),'0.500000')
        self.assertIsNotNone(tree.find('Root/Behavior/Decision'))
        lean=lean_program(tree,17,call)
        self.assertEqual(lean.get('name'),'use')
        self.assertIsNone(lean.find('.//Decision'))
        self.assertIsNone(lean.find('.//LuaGate'))
        self.assertTrue(all(n.get('Origin')=='$__object.id' and n[0].get('tag').startswith("'gm_sourceLean")
                            for n in lean.findall('.//GraphSearch')))

    def test_source_lean_selection_drift_rejected(self):
        tree=E.fromstring('''<BehaviorTree><Variables><Variable name="t_currentLean" isPersistent="1"/></Variables>
        <Root><OnInit><Sequence><IfElseCondition condition="$allowLeanBack"><Else><Expression expressions="$canChangeLean = false"/></Else></IfElseCondition>
        <IfCondition condition="$t_allowLeanLeft"><VarOperation operation="PushBack" varName="nextAllowedLeans" argument="leaningLeft"/></IfCondition>
        <IfCondition condition="$t_allowLeanRight"><VarOperation operation="PushBack" varName="nextAllowedLeans" argument="leaningRight"/></IfCondition>
        <IfCondition condition="$t_currentLean == ''"><RandomItem Array="nextAllowedLeans" Result="t_currentLean" Clamp="-1"/></IfCondition>
        </Sequence></OnInit><Behavior><IncludeTree File="final/so_templates.xml" Name="objectNewHelpers"/></Behavior></Root></BehaviorTree>''')
        validate_leaning(tree)
        tree.find('.//RandomItem').set('Clamp','1')
        with self.assertRaisesRegex(ValueError,'random leaning'):validate_leaning(tree)

    def test_source_threshold_no_mint_and_native_ownership_preserved(self):
        source,social,program,template=fixtures()
        t,b,r=opponent(source,social,program,template)
        self.assertEqual(r['minimum_groschen'],17)
        self.assertIsNone(b.find('.//CreateItem'))
        self.assertIsNone(b.find(".//Expression[@expressions='$hasEnoughMoney = true']"))
        self.assertIsNotNone(b.find(".//Expression[@expressions='$amountToCheck = 170']"))
        self.assertIsNotNone(b.find('.//IfElseCondition/Else/WaitAction'))
        self.assertEqual(t.get('BrainId'),'native-brain')
        self.assertEqual(t.find('.//InboxTemplate').get('InboxId'),'native-inbox')
        self.assertEqual(t.find('.//SmartBehaviorTemplate').get('InitialState'),'Disabled')
        self.assertIsNotNone(program.find('.//CreateItem'))

    def test_class_override_rejected(self):
        source,social,_,_=fixtures()
        with self.assertRaisesRegex(ValueError,'per-class'):minimum_bet(source,social+'\nSocialClass.data.a={diceMinimumBet=22,}')

    def test_unrecognized_money_grant_rejected(self):
        source,social,program,template=fixtures()
        program.find('.//CreateItem').set('Target','$someoneElse')
        with self.assertRaisesRegex(ValueError,'grants changed'):opponent(source,social,program,template)


if __name__=='__main__':unittest.main()
