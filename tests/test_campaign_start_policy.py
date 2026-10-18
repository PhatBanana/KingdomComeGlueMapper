import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_scene import attach_scene
from campaign_start_policy import POLICY, LEGACY_METHOD, gate_start, validate_native, validate_start_policy


def old_scene(blob, name='opening', guarded=False):
    root=ET.fromstring(blob); nodes=root.find('./Skald/Project/Nodes')
    arrival=nodes.find("State[@Name='"+name+"_ready']/Edge").get('From')
    for n in list(nodes):
        if n.get('Name') in [name+s for s in ('_game_start','_requested','_ready','_new_game')]: nodes.remove(n)
    nodes.find("If[@Name='"+name+"_begin']/Edge[@To='Exec']").set('From',arrival)
    if guarded:
        guard=ET.SubElement(nodes,'IfFunction',Name=name+'_new_game',MethodName=LEGACY_METHOD,DeclaringType='wh::rpgmodule')
        ET.SubElement(guard,'Edge',From=name+'_begin.True',To='Exec')
        nodes.find("TriggerSequence[@Name='"+name+"_initialize']/Edge").set('From',name+'_new_game.True')
        ET.SubElement(nodes.find("State[@Name='"+name+"_started']"),'Edge',From=name+'_new_game.False',To='SetTrue')
    return ET.tostring(root)


class CampaignStartPolicyTests(unittest.TestCase):
    def scene(self):
        host=b'<Database><Skald><Project><Definitions/><Nodes/><Types/><ObjectiveValueTypes/></Project></Skald></Database>'
        source=b'<Database><Skald><Project><Definitions/><Nodes><Quest Name="quest"/><Dialogue Name="opening"/></Nodes><Types/><ObjectiveValueTypes/></Project></Skald></Database>'
        return attach_scene(host,source,'opening','quest','region.arrived','Finished','player')

    def test_shared_builder_and_legacy_migration(self):
        blob=self.scene()
        self.assertEqual(validate_start_policy(blob,'opening'),POLICY)
        self.assertEqual(gate_start(blob,'opening'),blob)
        for guarded in (False,True):
            old=old_scene(blob,guarded=guarded)
            with self.assertRaises(ValueError):validate_start_policy(old,'opening')
            self.assertEqual(validate_start_policy(gate_start(old,'opening'),'opening'),POLICY)
        self.assertNotIn(LEGACY_METHOD.encode(),blob)

    def test_events_require_new_start_and_ready_and_run_only_once(self):
        # Interpret emitted control nodes, with each trigger chain dispatched before the next external event.
        # No game-start event is synthesized for load, arrival or return.
        nodes=ET.fromstring(self.scene()).find('./Skald/Project/Nodes')
        def run(events,state=None):
            state=dict(state or {}); effects=[]; queue=list(events)
            def value(ref):
                name,port=ref.rsplit('.',1)
                if name=='opening_unstarted': return not state.get('opening_started',False)
                return state.get(name,False)
            for _ in range(200):
                if not queue:return state,effects
                event=queue.pop(0)
                for node in nodes:
                    name=node.get('Name')
                    for edge in node.findall('Edge'):
                        if edge.get('From')!=event:continue
                        port=edge.get('To')
                        if node.tag=='State' and port in ('SetTrue','SetFalse'):
                            state[name]=port=='SetTrue';queue.insert(0,name+'.OnExec')
                        elif node.tag in ('If','IfFunction') and port=='Exec':
                            ports=['A','B'] if node.tag=='IfFunction' else ['Condition']
                            yes=all(value(node.find("Edge[@To='"+p+"']").get('From')) for p in ports)
                            queue.insert(0,name+('.True' if yes else '.False'))
                        elif node.tag=='TriggerSequence' and port=='Exec':
                            queue[0:0]=[name+'.'+p for p in 'ABC'];effects.append(name)
            raise AssertionError('Graph did not settle')
        for events in [('opening_game_start.OnStart','region.arrived'),('region.arrived','opening_game_start.OnStart')]:
            state,effects=run(events)
            self.assertEqual(effects,['opening_initialize'])
            self.assertFalse(state['opening_requested'])
            self.assertEqual(run(['region.arrived','opening_game_start.OnStart'],state)[1],[])
        self.assertEqual(run(['region.arrived','region.arrived'])[1],[])
        self.assertEqual(run([])[1],[])

    def test_bypass_rejected(self):
        root=ET.fromstring(self.scene());nodes=root.find('./Skald/Project/Nodes')
        ET.SubElement(nodes.find('TriggerSequence'),'Edge',From='region.arrived',To='Exec')
        with self.assertRaises(ValueError):validate_start_policy(ET.tostring(root),'opening')

    def test_native_contract_required(self):
        validate_native(b'<Definitions><Definition TypeName="GameStart"><Ports><CompileTimePort Name="OnStart" Direction="Out" Type="trigger"/></Ports></Definition></Definitions>')
        with self.assertRaises(ValueError):validate_native(b'<Definitions/>')
