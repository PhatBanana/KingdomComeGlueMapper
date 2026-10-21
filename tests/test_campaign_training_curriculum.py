import copy
import io
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_native_training import OUTPUTS
from campaign_training_curriculum import resolve, emit
from test_campaign_combat_runtime import Graph


PATH = 'Quests/Final/Arbitrary/lesson.xml'


def fixture():
    files = {}
    root = E.Element('Database'); host = E.SubElement(E.SubElement(root, 'Skald'), 'Gameplay', Name='lesson')
    defs = E.SubElement(host, 'Definitions'); nodes = E.SubElement(host, 'Nodes')
    native = E.SubElement(nodes, 'CombatTutorialNode', Name='native')
    E.SubElement(native, 'Constant', Name='Domain', Value='Basic')
    E.SubElement(native, 'Constant', Name='InitialPhase', Value='0')
    E.SubElement(native, 'Asset', Name='Tutor', Alias='trainer')
    E.SubElement(native, 'Edge', From='running.State', To='IsActive')
    switch = E.SubElement(nodes, 'Switch', Name='phase', SwitchValues='0 1 2')
    E.SubElement(switch, 'Edge', From='native.Phase', To='Switch')
    progress = E.SubElement(nodes, 'State', Name='progress')
    E.SubElement(progress, 'Edge', From='phase.Value1', To='Value')
    output = E.SubElement(nodes, 'Output', Name='Output')
    for port, _ in OUTPUTS.values(): E.SubElement(output, 'Edge', From='native.'+port, To=port)
    for i, alias in enumerate(('draw_0', 'chain_3', 'zone_7')):
        E.SubElement(switch, 'Constant', Name=str(i)+'Value1', Value=alias+'_starting')
        E.SubElement(progress, 'Edge', From='step'+str(i)+'.ready', To='Set'+alias+'_active')
        if i != 1: E.SubElement(native, 'Edge', From='step'+str(i)+'.ready', To='CustomStepEvent')
        E.SubElement(nodes, 'phase'+str(i), Name='step'+str(i))
        E.SubElement(defs, 'Definition', File='phase'+str(i)+'.xml')
        phase = E.fromstring(f'''<Database><Skald><Gameplay Name="phase{i}">
          <Definitions><Definition File="instruction{i}.xml"/></Definitions><Nodes>
          <State Name="active"><Edge From="speech.teach" To="SetActive"/></State>
          <instruction{i} Name="speech"/>
          <Output Name="Output"><Edge From="active.OnActive" To="ready"/></Output>
          <DisplayTutorial Name="ui"><Constant Name="Tutorial" Value="Native_{alias}"/>
            <Edge From="active.OnActive" To="Show"/></DisplayTutorial>
          </Nodes></Gameplay></Skald></Database>''')
        scene = E.fromstring(f'''<Database><Skald><ForcedDialog Name="instruction{i}">
          <Ports><Port Name="teach" Direction="Out" Type="trigger"/></Ports>
          <Dialogue><Decision Alias="native_{alias}"><Sequences><Sequence>
          <Triggers><Port Name="teach"/></Triggers><Elements><Response Role="ARBITRARY_TUTOR"/>
          </Elements></Sequence></Sequences></Decision></Dialogue>
          </ForcedDialog></Skald></Database>''')
        files[f'Quests/Final/Arbitrary/phase{i}.xml'] = E.tostring(phase)
        files[f'Quests/Final/Arbitrary/instruction{i}.xml'] = E.tostring(scene)
    files[PATH] = E.tostring(root)
    return files


def archive(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for p, b in files.items(): z.writestr(p, b)
    return zipfile.ZipFile(buf)


class InstructionGraph(Graph):
    def fire(self, event):
        super().fire(event)
        for name, node in self.nodes.items():
            if node.tag != 'IfFunction' or node.find("Edge[@From='"+event+"'][@To='Exec']") is None:
                continue
            self.assert_compare(node)
            value = self.value(node.find("Edge[@To='ValueA']").get('From'))
            expected = int(node.find("Constant[@Name='ValueB']").get('Value'))
            self.fire(name+('.True' if value == expected else '.False'))

    @staticmethod
    def assert_compare(node):
        assert node.get('MethodName') == 'Control::Compare'
        assert node.find("Constant[@Name='Op']").get('Value') == 'Equals'


class NativeCurriculumTests(unittest.TestCase):
    def test_follows_native_graph_instead_of_alias_numbers(self):
        files = fixture(); before = copy.deepcopy(files)
        with archive(files) as z: plan = resolve(z, PATH, 'Basic')
        self.assertEqual([p['phase'] for p in plan['phases']], [0,1,2])
        self.assertEqual([p['instruction_aliases'] for p in plan['phases']],
                         [['native_draw_0'], ['native_chain_3'], ['native_zone_7']])
        self.assertEqual([p['custom_step'] for p in plan['phases']], [True,False,True])
        self.assertEqual(files, before)

    def test_emits_native_exercises_with_tracker_and_cleanup_boundary(self):
        with archive(fixture()) as z: blob, report = emit('AnyLesson', z, PATH, 'Basic')
        root = E.fromstring(blob)
        self.assertEqual(root.find('.//Output/Edge[@To="tracker"]').get('From'), 'training.Tracker')
        self.assertEqual(root.find('.//CombatTutorialNode/Constant[@Name="InitialPhase"]').get('Value'), '0')
        self.assertNotEqual(root.find('.//Output/Edge[@To="finished"]').get('From'), 'training.OnTutorialEnd')
        self.assertFalse(report['faction_conversion_required'])
        self.assertFalse(report['source_exercises_reproduced'])
        self.assertFalse(report['runtime_validated'])

    def test_rejects_wrong_domain_incomplete_range_missing_tracker_and_nonproduction(self):
        for change in ('domain','range','tracker','nonproduction'):
            files=fixture(); path=PATH
            root=E.fromstring(files[path])
            if change=='domain': root.find('.//Constant[@Name="Domain"]').set('Value','Other')
            if change=='range': root.find('.//Switch').set('SwitchValues','0 2 3')
            if change=='tracker':
                output=root.find('.//Output'); output.remove(output.find('Edge[@From="native.Tracker"]'))
            files[path]=E.tostring(root)
            if change=='nonproduction': path='Quests/Testing/lesson.xml'; files[path]=files[PATH]
            with self.subTest(change=change),archive(files) as z,self.assertRaises(ValueError):
                resolve(z,path,'Basic')

    def test_cycle_and_missing_authored_cue_are_rejected(self):
        for change in ('cycle','cue'):
            files=fixture()
            if change=='cycle':
                p='Quests/Final/Arbitrary/phase0.xml'; r=E.fromstring(files[p])
                r.find('.//State/Edge').set('From','active.OnActive')
            else:
                p='Quests/Final/Arbitrary/instruction0.xml'; r=E.fromstring(files[p])
                r.find('.//Triggers').clear()
            files[p]=E.tostring(r)
            with self.subTest(change=change),archive(files) as z,self.assertRaises(ValueError): resolve(z,PATH,'Basic')



if __name__ == '__main__': unittest.main()
