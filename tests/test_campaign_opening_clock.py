from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_opening_clock import source_clock, bind


class OpeningClockTests(unittest.TestCase):
    def source(self, code='forwardTime(10.00)', nested=False):
        root=E.Element('BehaviorTrees');tree=E.SubElement(root,'BehaviorTree',name='opening')
        seq=E.SubElement(E.SubElement(E.SubElement(tree,'Root'),'Behavior'),'Sequence')
        E.SubElement(E.SubElement(seq,'IfCondition') if nested else seq,'ExecuteLua',code=code)
        E.SubElement(seq,'PlayCutscene',name='intro')
        return E.tostring(root)

    def graph(self):
        from campaign_scene import attach_scene
        host=b'<Database><Skald><Project><Definitions/><Nodes/><Types/><ObjectiveValueTypes/></Project></Skald></Database>'
        source=b'<Database><Skald><Project><Definitions/><Nodes><Quest Name="quest"/><Dialogue Name="open"/></Nodes><Types/><ObjectiveValueTypes/></Project></Skald></Database>'
        root=E.fromstring(attach_scene(host,source,'open','quest','region.arrived','Finished','player'))
        nodes=root.find('./Skald/Project/Nodes')
        # Replace the default B consumer with a representative loadout call.
        for edge in nodes.findall("*/Edge[@From='open_initialize.B']"):
            for parent in nodes:
                if edge in list(parent):parent.remove(edge)
        E.SubElement(E.SubElement(nodes,'Function',Name='loadout'),'Edge',From='open_initialize.B',To='Exec')
        E.SubElement(E.SubElement(nodes,'Function',Name='restore'),'Edge',From='OnLoad',To='Exec')
        return E.tostring(root)

    def test_source_hour_not_a_fixed_skalitz_constant(self):
        for hour in ('10.00','7.25','23.5'):
            plan=source_clock(self.source('forwardTime('+hour+"); Utils.SetWorldTimePaused(true, 'intro')"),'opening')
            self.assertEqual(float(plan['hour']),float(hour))
            out=bind(self.graph(),plan,'open');r=E.fromstring(out)
            call=r.find(".//Function[@Name='open_source_clock']")
            self.assertEqual(call.find('Constant').get('Value'),{'10.00':'10h00m','7.25':'07h15m','23.5':'23h30m'}[hour])
            self.assertEqual(r.find(".//Function[@Name='loadout']/Edge").get('From'),'open_source_clock.OnExec')
            self.assertEqual(r.find(".//Function[@Name='restore']/Edge").get('From'),'OnLoad')
            self.assertEqual(out,bind(out,plan,'open'))
            self.assertIsNone(r.find('.//PauseWorldTime'))
            from campaign_start_policy import validate_start_policy, gate_start
            validate_start_policy(out,'open')
            self.assertEqual(gate_start(out,'open'),out)

    def test_migrates_console_clock_without_replaying_or_rebinding_start(self):
        plan=source_clock(self.source(),'opening')
        native=bind(self.graph(),plan,'open')
        root=E.fromstring(native); call=root.find(".//Function[@Name='open_source_clock']")
        call.set('MethodName','wh::conceptmodule::ExecuteConsoleString');call.set('DeclaringType','wh::conceptmodule')
        call.find('Constant').attrib.update(Name='Command',Value='#forwardTime(10)')
        repaired=bind(E.tostring(root),plan,'open')
        self.assertEqual(repaired,native)

    def test_valid_clock_preserves_unrelated_native_resource_formatting(self):
        plan=source_clock(self.source(),'opening')
        root=E.fromstring(bind(self.graph(),plan,'open'))
        # Later stages append native types/assets without normalizing the whole
        # project. Reapplying the clock must preserve those exact packaged bytes.
        types=root.find('Skald/Project/Types')
        types.append(E.fromstring('<Type TypeName="NativeGameState">\n\t<Enum Value="Waiting" />\n</Type>'))
        E.SubElement(root.find('Skald/Project'),'Assets').append(
            E.fromstring('<SoulAsset Name="native_actor"\n\tSharedSoulGuids="actor" />'))
        payload=E.tostring(root,encoding='utf-8',xml_declaration=True)
        self.assertEqual(bind(payload,plan,'open'),payload)

    def test_ambiguous_conditional_and_compound_scripts_are_rejected(self):
        for blob in (self.source(nested=True),self.source('forwardTime(10); forwardTime(16)'),
                     self.source('forwardTime(10); doOtherWork()'),self.source('forwardTime(24)')):
            with self.assertRaises(ValueError):source_clock(blob,'opening')

    def test_load_hook_and_tampering_cannot_reset_clock(self):
        plan=source_clock(self.source(),'opening')
        with self.assertRaises(ValueError):bind(self.graph().replace(b'open_new_game.True',b'OnLoad'),plan,'open')
        out=bind(self.graph(),plan,'open')
        with self.assertRaises(ValueError):bind(out.replace(b'10h00m',b'12h00m'),plan,'open')


if __name__=='__main__':unittest.main()
